#!/usr/bin/env bash
# Run ON THE VPS (Ubuntu/Debian) as root, from the folder holding bot.py, app.py,
# requirements.txt and your filled-in .env:   sudo bash deploy_vps.sh
set -e
APP=/opt/groktrader
[ -f .env ] || { echo "Missing .env. Run: cp .env.example .env && nano .env"; exit 1; }
grep -q '^APP_PASSWORD=choose' .env && { echo "Change APP_PASSWORD in .env first"; exit 1; }
apt-get update -y && apt-get install -y python3 python3-venv
mkdir -p $APP
cp bot.py app.py requirements.txt .env $APP/
chmod 600 $APP/.env
python3 -m venv $APP/venv
$APP/venv/bin/pip install -q -r $APP/requirements.txt
cat > /etc/systemd/system/groktrader.service <<UNIT
[Unit]
Description=Grok Trader
After=network-online.target
[Service]
WorkingDirectory=$APP
ExecStart=$APP/venv/bin/python app.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now groktrader
sleep 2
systemctl --no-pager --lines=5 status groktrader || true
IP=$(curl -s -m 5 ifconfig.me || echo YOUR_SERVER_IP)
echo
echo "Dashboard: http://$IP:8080   (login: any username, password from .env)"
echo "Logs:      journalctl -u groktrader -f"
echo "Open port 8080 in your VPS provider firewall if the page does not load."
