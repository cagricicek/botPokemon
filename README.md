# Pokémon Center UK – TCG Stok Takibi → Telegram

Her 5 dakikada bir [TCG Cards](https://www.pokemoncenter.com/en-gb/category/tcg-cards?sort=launch_date%2Bdesc) sayfasındaki en yeni 96 ürünü kontrol eder. Bir ürün **SOLD OUT → stokta** geçerse Telegram'a mesaj atar. GitHub Actions üzerinde ücretsiz, 7/24 çalışır.

## Kurulum (yaklaşık 10 dakika)

### 1. Telegram botu oluştur
1. Telegram'da **@BotFather**'a yaz → `/newbot` → bota isim ver.
2. Verdiği **token**'ı kopyala (ör. `123456:ABC-...`).
3. Yeni botuna Telegram'dan bir mesaj at (ör. "merhaba"). Bu adım şart, yoksa bot sana yazamaz.
4. Tarayıcıda şunu aç (TOKEN yerine kendi token'ın):
   `https://api.telegram.org/botTOKEN/getUpdates`
   Çıkan yazıda `"chat":{"id":123456789` kısmındaki sayı senin **chat ID**'n.

### 2. GitHub reposu oluştur
1. github.com'da yeni bir repo aç → **Public** seç.
   (Public repoda Actions dakikaları sınırsız ve ücretsiz. Private'ta ayda 2.000 dakika sınırı var, 5 dakikalık kontrol bunu birkaç günde bitirir. Token'lar Secrets'ta durduğu için public olması güvenli.)
2. Bu klasördeki dosyaları repoya yükle. `.github/workflows/monitor.yml` dosyasının klasör yapısı korunmalı.
   - En kolayı: repo sayfasında **Add file → Upload files** ve klasörün içeriğini sürükle-bırak. Gizli `.github` klasörü görünmüyorsa Mac'te Finder'da `Cmd + Shift + .` ile görünür yap.

### 3. Secret'ları ekle
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Ad | Değer |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather'ın verdiği token |
| `TELEGRAM_CHAT_ID` | getUpdates'ten aldığın sayı |

### 4. Çalıştır
Repo → **Actions** sekmesi → (gerekirse "I understand… enable" butonuna bas) → **Pokémon Center stok takibi** → **Run workflow**.

İlk çalışmada Telegram'a "✅ Stok takibi başladı" mesajı gelir. Sonrasında sadece stoğa giren ürünler için bildirim gelir.

## Bilinmesi gerekenler
- **Gecikme:** GitHub zamanlanmış işleri her zaman tam 5 dakikada çalıştırmaz; yoğun saatlerde 10–15 dakika kayabilir.
- **Bot koruması:** Pokémon Center bot koruması kullanıyor ve veri merkezi IP'lerini zaman zaman engelleyebiliyor. Sayfa art arda 6 kez okunamazsa Telegram'a bir uyarı gelir; tekrar okunmaya başlayınca yine haber verir. Sürekli engellenirse script'i kendi bilgisayarında çalıştırmak daha güvenilir olur.
- **60 gün kuralı:** Repoda 60 gün hiçbir hareket olmazsa GitHub zamanlanmış işi durdurur. Böyle olursa Actions sekmesinden tekrar etkinleştirmen yeterli.
- **Daha fazla ürün izlemek:** Varsayılan olarak en yeni 96 ürün izlenir. `monitor.yml` içindeki "Stok kontrolü" adımına `PAGES: "2"` ekleyerek 192'ye çıkarabilirsin.

## Kendi bilgisayarında denemek (isteğe bağlı)
```bash
pip install -r requirements.txt
python -m playwright install chromium
export TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="..."
python monitor.py --test   # sadece test mesajı
python monitor.py          # gerçek kontrol
```
