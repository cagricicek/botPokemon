#!/bin/bash
# Pokémon Center stok takibi - Ubuntu sunucu kurulumu
# Kullanım (sunucuda, root olarak):
#   curl -fsSL https://raw.githubusercontent.com/cagricicek/botPokemon/main/sunucu-kur.sh | bash
set -e

REPO_RAW="https://raw.githubusercontent.com/cagricicek/botPokemon/main"
APP=/opt/pokebot
INTERVAL_MIN=2

echo "=== Pokémon Center stok takibi - sunucu kurulumu ==="

# 1) Sistem paketleri
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip xvfb curl >/dev/null
echo "✓ Sistem paketleri kuruldu"

# 2) RAM azsa swap ekle (Chrome için)
if [ "$(free -m | awk '/Mem:/{print $2}')" -lt 1800 ] && ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "✓ 1 GB swap eklendi"
fi

# 3) Bot dosyaları
mkdir -p "$APP"
curl -fsSL "$REPO_RAW/monitor.py" -o "$APP/monitor.py"
curl -fsSL "$REPO_RAW/requirements.txt" -o "$APP/requirements.txt"
echo "✓ Bot dosyaları indirildi"

# 4) Python ortamı ve tarayıcı
[ -x "$APP/venv/bin/python" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"
export PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=600000
"$APP/venv/bin/python" -m playwright install-deps chromium >/dev/null
# Önce Google Chrome (dl.google.com'dan iner), olmazsa Playwright Chromium
if ! command -v google-chrome >/dev/null 2>&1; then
  echo "… Google Chrome kuruluyor"
  "$APP/venv/bin/python" -m playwright install chrome >/dev/null 2>&1 || true
fi
if command -v google-chrome >/dev/null 2>&1; then
  echo "✓ Google Chrome kuruldu"
else
  echo "… Chrome kurulamadı, Playwright Chromium indiriliyor"
  "$APP/venv/bin/python" -m playwright install chromium
fi
echo "✓ Python ve tarayıcı hazır"

# 5) Telegram bilgileri
if [ ! -f "$APP/.env" ]; then
  echo
  echo "Telegram bot token'ını yapıştır (görünmez) ve Enter'a bas:"
  read -r -s TOKEN < /dev/tty
  TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
  echo
  read -r -p "Telegram chat ID [1655563740]: " CHAT < /dev/tty
  CHAT="${CHAT:-1655563740}"
  umask 077
  cat > "$APP/.env" <<EOF
export TELEGRAM_BOT_TOKEN='$TOKEN'
export TELEGRAM_CHAT_ID='$CHAT'
export PAGE_SIZE='96'
export HEADLESS='0'
EOF
fi

# 6) Çalıştırma betiği
cat > "$APP/run.sh" <<'EOF'
#!/bin/bash
cd /opt/pokebot
source ./.env
LOG=./bot.log
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG")" -gt 1048576 ]; then : > "$LOG"; fi
echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---" >> "$LOG"
xvfb-run -a ./venv/bin/python monitor.py "$@" >> "$LOG" 2>&1
EOF
chmod +x "$APP/run.sh"

# 7) Testler
echo
echo "… Telegram test mesajı gönderiliyor"
(cd "$APP" && source ./.env && ./venv/bin/python monitor.py --test)
echo "… Pokémon Center ilk kez kontrol ediliyor (30-60 sn)"
(cd "$APP" && source ./.env && xvfb-run -a ./venv/bin/python monitor.py) || true

# 8) Her 2 dakikada bir otomatik çalıştır (systemd timer)
cat > /etc/systemd/system/pokebot.service <<EOF
[Unit]
Description=Pokemon Center stok kontrolu
[Service]
Type=oneshot
ExecStart=$APP/run.sh
TimeoutStartSec=300
EOF
cat > /etc/systemd/system/pokebot.timer <<EOF
[Unit]
Description=Pokemon Center stok kontrolu (her ${INTERVAL_MIN} dk)
[Timer]
OnBootSec=1min
OnUnitActiveSec=${INTERVAL_MIN}min
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now pokebot.timer >/dev/null

echo
echo "=============================================="
echo " ✓ Kurulum tamam. Bot her ${INTERVAL_MIN} dakikada bir çalışacak."
echo "   Son kayıtlar:   tail -n 30 $APP/bot.log"
echo "   Durdurmak için: systemctl disable --now pokebot.timer"
echo "=============================================="
