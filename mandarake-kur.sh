#!/bin/bash
# Mandarake yeni ilan takibi - sunucu kurulumu
# Önce sunucu-kur.sh ile temel kurulum yapılmış olmalı (/opt/pokebot).
# Kullanım (sunucuda, root olarak):
#   curl -fsSL https://raw.githubusercontent.com/cagricicek/botPokemon/main/mandarake-kur.sh | bash
set -e

REPO_RAW="https://raw.githubusercontent.com/cagricicek/botPokemon/main"
APP=/opt/pokebot
INTERVAL_MIN=5

if [ ! -x "$APP/venv/bin/python" ] || [ ! -f "$APP/.env" ]; then
  echo "Önce temel kurulumu yap: curl -fsSL $REPO_RAW/sunucu-kur.sh | bash"
  exit 1
fi

echo "=== Mandarake takibi kuruluyor ==="
curl -fsSL "$REPO_RAW/mandarake.py" -o "$APP/mandarake.py"
echo "✓ mandarake.py indirildi"

cat > "$APP/run_mandarake.sh" <<'EOF'
#!/bin/bash
cd /opt/pokebot
source ./.env
unset PROXY_URL
LOG=./mandarake.log
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG")" -gt 1048576 ]; then : > "$LOG"; fi
echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---" >> "$LOG"
xvfb-run -a ./venv/bin/python mandarake.py "$@" >> "$LOG" 2>&1
EOF
chmod +x "$APP/run_mandarake.sh"

echo "… İlk kontrol yapılıyor (mevcut ilanlar kaydedilecek, 30-60 sn)"
(cd "$APP" && source ./.env && unset PROXY_URL && xvfb-run -a ./venv/bin/python mandarake.py) || true

cat > /etc/systemd/system/mandarake.service <<EOF
[Unit]
Description=Mandarake yeni ilan kontrolu
[Service]
Type=oneshot
ExecStart=$APP/run_mandarake.sh
TimeoutStartSec=300
EOF
cat > /etc/systemd/system/mandarake.timer <<EOF
[Unit]
Description=Mandarake yeni ilan kontrolu (her ${INTERVAL_MIN} dk)
[Timer]
OnBootSec=2min
OnUnitActiveSec=${INTERVAL_MIN}min
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now mandarake.timer >/dev/null

echo
echo "=============================================="
echo " ✓ Mandarake takibi kuruldu (her ${INTERVAL_MIN} dakikada bir)."
echo "   Son kayıtlar:   tail -n 30 $APP/mandarake.log"
echo "   Durdurmak için: systemctl disable --now mandarake.timer"
echo "=============================================="
