"""
Mandarake - yeni ilan takipçisi (Beyblade).

Arama sayfasını (en yeni ilanlar en üstte) gerçek bir tarayıcıyla açar,
daha önce görülmemiş bir ilan çıkarsa Telegram'a fotoğraflı bildirim atar.
İlk çalıştırmada mevcut ilanları sadece kaydeder, bildirim göndermez.

Kullanım:
    python mandarake.py          # normal kontrol
    python mandarake.py --test   # Telegram'a test mesajı
"""

from __future__ import annotations

import html
import json
import os
import sys
import time
from pathlib import Path

import requests

# ---------------- Ayarlar ----------------
SEARCH_URL = os.getenv(
    "MANDARAKE_URL",
    "https://order.mandarake.co.jp/order/listPage/list?keyword=Beyblade&lang=en&deviceId=1",
)
DISP_COUNT = int(os.getenv("MANDARAKE_COUNT", "120"))  # sayfa başına ilan (48 / 120 / 240)
NOTIFY_SOLD_OUT = os.getenv("MANDARAKE_NOTIFY_SOLD_OUT", "0") == "1"
MAX_ALERTS_PER_RUN = 15  # bir seferde bundan fazla yeni ilan çıkarsa özet gönder
STATE_FILE = Path(__file__).with_name("mandarake_state.json")
FAIL_ALERT_AFTER = 6
MAX_SEEN = 10000

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DETAIL_URL = "https://order.mandarake.co.jp/order/detailPage/item?itemCode={}&lang=en"


# ---------------- Telegram ----------------
def _tg(method: str, payload: dict) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[uyarı] Telegram ayarlı değil. {method}: {payload.get('text') or payload.get('caption')}")
        return True
    payload = {"chat_id": TELEGRAM_CHAT_ID, "parse_mode": "HTML", **payload}
    for _ in range(3):
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", json=payload, timeout=30)
        if r.ok:
            return True
        if r.status_code == 429:  # çok hızlı gönderim
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5) + 1)
            continue
        print(f"[hata] Telegram {r.status_code}: {r.text[:200]}")
        return False
    return False


def send_text(text: str) -> None:
    _tg("sendMessage", {"text": text, "disable_web_page_preview": True})


def send_item(item: dict) -> None:
    caption = (
        "🆕 <b>Mandarake'te yeni ilan</b>\n"
        f"{html.escape(item['title'])}\n"
        f"💴 {html.escape(item['price'])}"
        + (f" · 🏬 {html.escape(item['shop'])}" if item.get("shop") else "")
        + ("\n⚠️ Tükenmiş" if item["sold_out"] else "")
        + f'\n<a href="{item["url"]}">İlana git</a>'
    )
    if item.get("image") and _tg("sendPhoto", {"photo": item["image"], "caption": caption}):
        return
    send_text(caption)


# ---------------- Veri çekme ----------------
EXTRACT_JS = """
() => [...document.querySelectorAll('.block[data-itemidx]')].map(b => {
  const a = b.querySelector('.title a');
  const img = b.querySelector('.thum img');
  return {
    id: b.getAttribute('data-itemidx'),
    title: (a ? a.innerText : '').trim(),
    price: ((b.querySelector('.price') || {}).innerText || '').trim(),
    shop: ((b.querySelector('.shop') || {}).innerText || '').trim(),
    image: img ? (img.getAttribute('data-src') || img.src || '') : '',
    sold_out: !!b.querySelector('.soldout'),
  };
})
"""


def build_url() -> str:
    sep = "&" if "?" in SEARCH_URL else "?"
    url = SEARCH_URL
    if "dispCount=" not in url:
        url += f"{sep}dispCount={DISP_COUNT}"
        sep = "&"
    if "sort=" not in url:  # en yeni ilanlar en üstte
        url += f"{sep}sort=arrival&sortOrder=1"
    return url


def normalize(raw: list[dict]) -> list[dict]:
    items = []
    for r in raw:
        if not r.get("id"):
            continue
        img = r.get("image") or ""
        if img.startswith("/"):
            img = "https://order.mandarake.co.jp" + img
        if "loader.gif" in img:
            img = ""
        items.append({**r, "image": img, "url": DETAIL_URL.format(r["id"])})
    return items


def fetch_items() -> list[dict]:
    from playwright.sync_api import sync_playwright

    url = build_url()
    headless = os.getenv("HEADLESS", "1") != "0"
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=headless)
        except Exception:  # noqa: BLE001
            browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(locale="en-US", viewport={"width": 1366, "height": 900})
        # Resim/font indirmeye gerek yok
        context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media", "font"}
            else route.continue_(),
        )
        page = context.new_page()
        try:
            raw: list[dict] = []
            # İlk ziyarette site çerez verip ana sayfaya yönlendirebiliyor; bu yüzden 3 deneme
            for attempt in range(3):
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_selector(".block[data-itemidx]", state="attached", timeout=15_000)
                except Exception:  # noqa: BLE001
                    if "Goods could not be found" in page.content():
                        return []
                    print(f"[bilgi] Liste görünmedi ({attempt + 1}. deneme), adres: {page.url}")
                    continue
                raw = page.evaluate(EXTRACT_JS)
                break
            if not raw:
                title = page.title()
                body = page.inner_text("body")[:300].replace("\n", " ")
                raise RuntimeError(f"İlan listesi okunamadı. Başlık: {title!r} | Sayfa: {body!r}")
            return normalize(raw)
        finally:
            browser.close()


# ---------------- Durum ----------------
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def find_new(seen: set[str], items: list[dict]) -> list[dict]:
    return [i for i in items if i["id"] not in seen]


# ---------------- Ana akış ----------------
def main() -> int:
    if "--test" in sys.argv:
        send_text("✅ Mandarake takipçisi çalışıyor. Bu bir test mesajıdır.")
        return 0

    state = load_state()
    seen_list: list[str] = state.get("seen", [])
    seen = set(seen_list)
    first_run = not seen

    try:
        items = fetch_items()
    except Exception as e:  # noqa: BLE001
        fails = state.get("consecutive_failures", 0) + 1
        state["consecutive_failures"] = fails
        print(f"[hata] Mandarake okunamadı ({fails}. kez): {e}")
        if fails == FAIL_ALERT_AFTER:
            send_text(f"⚠️ Mandarake sayfası art arda {fails} kez okunamadı.")
        save_state(state)
        return 0

    new_items = find_new(seen, items)
    if first_run:
        send_text(
            "✅ Mandarake takibi başladı.\n"
            f"Şu anki {len(items)} ilan kaydedildi; bundan sonra sadece yeni gelen ilanlar bildirilecek."
        )
    else:
        alerts = [i for i in new_items if NOTIFY_SOLD_OUT or not i["sold_out"]]
        if len(alerts) > MAX_ALERTS_PER_RUN:
            lines = "\n".join(f'• <a href="{i["url"]}">{html.escape(i["title"][:70])}</a> – {html.escape(i["price"])}' for i in alerts[:30])
            send_text(f"🆕 <b>Mandarake'te {len(alerts)} yeni ilan</b>\n{lines}")
        else:
            for i in reversed(alerts):  # eskiden yeniye sırayla
                send_item(i)
                time.sleep(1.5)

    if state.get("consecutive_failures", 0) >= FAIL_ALERT_AFTER:
        send_text("✅ Mandarake sayfası yeniden okunabiliyor.")

    for i in items:
        if i["id"] not in seen:
            seen.add(i["id"])
            seen_list.append(i["id"])
    state["seen"] = seen_list[-MAX_SEEN:]
    state["consecutive_failures"] = 0
    save_state(state)
    print(f"{len(items)} ilan kontrol edildi, {len(new_items)} yeni.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
