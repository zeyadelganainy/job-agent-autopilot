#!/usr/bin/env bash
# Provision job-agent-autopilot on a fresh Ubuntu VM (e.g. Oracle Cloud Always Free).
# Run on the VM:  bash deploy/install.sh   (after cloning the repo), or curl it down first.
set -euo pipefail

REPO_URL="https://github.com/zeyadelganainy/job-agent-autopilot.git"
APP_DIR="$HOME/job-agent-autopilot"

sudo apt-get update
sudo apt-get install -y python3-venv python3-pip git curl debian-keyring debian-archive-keyring apt-transport-https

# Caddy (automatic HTTPS reverse proxy) from the official repo
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update && sudo apt-get install -y caddy
fi

# Code + venv
[ -d "$APP_DIR/.git" ] || git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cat <<'NEXT'

Installed. Finish setup:
  1) From your laptop, push secrets + profile (kept out of the public repo):
        ./deploy/sync-secrets.sh ubuntu@<vm-ip>
     Then on the VM, fill in .env (WEB_PASSWORD, ANTHROPIC/GEMINI keys, SMTP_*, APP_URL).
  2) Point a free DuckDNS subdomain at this VM's public IP, edit deploy/Caddyfile, then:
        sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy
  3) Install + start the service:
        sudo cp deploy/jobagent.service /etc/systemd/system/
        sudo systemctl daemon-reload && sudo systemctl enable --now jobagent
  4) Open ingress for ports 80 + 443 in the Oracle VCN security list.
NEXT
