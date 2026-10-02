"""
Pokémon Center UK - TCG kartları stok takipçisi.

Kategori sayfasını gerçek bir tarayıcıyla (Playwright/Chromium) açar,
sayfanın içindeki __NEXT_DATA__ JSON'undan ürünleri ve stok durumlarını okur.
Bir ürün "tükendi"den "stokta"ya geçerse (veya yeni bir ürün stokta eklenirse)
Telegram'a bildirim atar.

Kullanım:
    python monitor.py          # normal kontrol
    python monitor.py --test   # sadece Telegram'a test mesajı gönderir
"""

import html
import json
import os
import sys
import time
from pathlib import Path

import requests

# ---------------- Ayarlar ----------------
BASE = "https://www.pokemoncenter.com"
CATEGORY_URL = BASE + "/en-gb/category/tcg-cards?sort=launch_date%2Bdesc&ps=96"
PAGES = int(os.getenv("PAGES", "1"))  # 1 sayfa = en yeni 96 ürün
STATE_FILE = Path(__file__).with_name("state.json")
FAIL_ALERT_AFTER = 6  # art arda bu kadar başarısız denemede bir kez uyar

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


# ---------------- Telegram ----------------
def send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[uyarı] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID tanımlı değil. Mesaj:\n" + text)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    if not r.ok:
        print(f"[hata] Telegram {r.status_code}: {r.text}")


# ---------------- Veri çekme ----------------
def parse_products(next_data: dict) -> list[dict]:
    """__NEXT_DATA__ içinden ürün listesini sade bir forma çevirir."""
    results = next_data["props"]["initialState"]["search"]["results"]
    products = []
    for p in results.get("products", []):
        code = p.get("code")
        if not code:
            continue
        price = (p.get("purchasePrice") or p.get("listPrice") or {}).get("display", "")
        products.append(
            {
                "code": code,
                "name": p.get("name", code),
                "price": price,
                "in_stock": not p.get("outOfStock", True),
                "url": f"{BASE}/en-gb/product/{code}",
            }
        )
    return products


def fetch_products() -> list[dict]:
    from playwright.sync_api import sync_playwright

    headless = os.getenv("HEADLESS", "1") != "0"
    launch_args = dict(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )

    all_products: list[dict] = []
    with sync_playwright() as pw:
        # Mümkünse gerçek Google Chrome'u kullan (bot korumasına daha az takılır)
        try:
            browser = pw.chromium.launch(channel="chrome", **launch_args)
            print("Tarayıcı: Google Chrome", "(headless)" if headless else "(görünür)")
        except Exception:  # noqa: BLE001
            browser = pw.chromium.launch(**launch_args)
            print("Tarayıcı: Playwright Chromium", "(headless)" if headless else "(görünür)")

        context = browser.new_context(
            locale="en-GB",
            timezone_id="Europe/London",
            viewport={"width": 1366, "height": 900},
            **({"user_agent": USER_AGENT} if headless else {}),
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.new_page()
        try:
            for i in range(1, PAGES + 1):
                url = CATEGORY_URL + (f"&page={i}" if i > 1 else "")
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                # Bot koruması önce bir JS kontrol sayfası gösterebiliyor; asıl sayfa gelene kadar bekle.
                page.wait_for_selector("script#__NEXT_DATA__", state="attached", timeout=60_000)
                raw = page.eval_on_selector("script#__NEXT_DATA__", "el => el.textContent")
                all_products.extend(parse_products(json.loads(raw)))
                time.sleep(2)
        except Exception:
            # Teşhis için sitenin ne gösterdiğini loga yaz
            try:
                body = page.inner_text("body")[:400].replace("\n", " ")
                print(f"[teşhis] Başlık: {page.title()!r} | Sayfa: {body!r}")
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            browser.close()
    return all_products


# ---------------- Durum ----------------
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def find_restocks(previous: dict, products: list[dict]) -> list[dict]:
    """Önceden stokta olmayan (veya hiç görülmemiş) ama şimdi stokta olan ürünler."""
    return [p for p in products if p["in_stock"] and not previous.get(p["code"], False)]


def format_message(p: dict) -> str:
    return (
        "🟢 <b>STOKTA!</b>\n"
        f"{html.escape(p['name'])}\n"
        f"💷 {html.escape(p['price'])}\n"
        f'<a href="{p["url"]}">Ürüne git</a>'
    )


# ---------------- Ana akış ----------------
def main() -> int:
    if "--test" in sys.argv:
        send_telegram("✅ Pokémon Center stok takipçisi çalışıyor. Bu bir test mesajıdır.")
        return 0

    state = load_state()
    stock: dict = state.get("stock", {})
    first_run = not stock

    try:
        products = fetch_products()
        if not products:
            raise RuntimeError("Sayfada ürün bulunamadı")
    except Exception as e:  # noqa: BLE001
        fails = state.get("consecutive_failures", 0) + 1
        state["consecutive_failures"] = fails
        print(f"[hata] Sayfa okunamadı ({fails}. kez): {e}")
        if fails == FAIL_ALERT_AFTER:
            send_telegram(
                "⚠️ Pokémon Center sayfası art arda "
                f"{fails} kez okunamadı. Site bot korumasıyla engelliyor olabilir."
            )
        save_state(state)
        return 0  # workflow'u kırmızıya boyamamak için

    restocks = find_restocks(stock, products)
    if first_run:
        in_stock_now = [p for p in products if p["in_stock"]]
        send_telegram(
            "✅ Stok takibi başladı.\n"
            f"{len(products)} ürün izleniyor, şu an stokta olan: {len(in_stock_now)}."
        )
    else:
        for p in restocks:
            send_telegram(format_message(p))
            time.sleep(1)

    if state.get("consecutive_failures", 0) >= FAIL_ALERT_AFTER:
        send_telegram("✅ Pokémon Center sayfası yeniden okunabiliyor.")

    # Yeni durumu kaydet (sayfadan düşen ürünlerin eski kaydı korunur)
    for p in products:
        stock[p["code"]] = p["in_stock"]
    state["stock"] = stock
    state["consecutive_failures"] = 0
    save_state(state)

    print(f"{len(products)} ürün kontrol edildi, {len(restocks)} yeni stok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
