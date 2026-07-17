#!/usr/bin/env bash
# Provision job-agent-autopilot on a fresh Ubuntu VM (e.g. Oracle Cloud Always Free).
# Run on the VM:  git clone … && cd job-agent-autopilot && bash deploy/install.sh
set -euo pipefail

REPO_URL="https://github.com/zeyadelganainy/job-agent-autopilot.git"
APP_DIR="$HOME/job-agent-autopilot"

sudo apt-get update
sudo apt-get install -y git curl debian-keyring debian-archive-keyring apt-transport-https

# Caddy (automatic HTTPS reverse proxy) from the official repo
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update && sudo apt-get install -y caddy
fi

# uv installs a standalone Python 3.11 — no system Python needed (older distros ship 3.8,
# which the app's syntax won't run on, and deadsnakes can be unreliable).
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# Code + venv (managed Python 3.11) + deps
[ -d "$APP_DIR/.git" ] || git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

cat <<'NEXT'

Installed. Finish setup:
  1) From your laptop, push secrets + profile (kept out of the public repo):
        ./deploy/sync-secrets.sh ubuntu@<vm-ip>
     Then on the VM, ensure .env has WEB_PASSWORD, ANTHROPIC/FALLBACK keys, SMTP_*, APP_URL.
  2) Point a free DuckDNS subdomain at this VM's public IP, edit deploy/Caddyfile, then:
        sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy
  3) Install + start the service:
        sudo cp deploy/jobagent.service /etc/systemd/system/
        sudo systemctl daemon-reload && sudo systemctl enable --now jobagent
  4) Open ingress for ports 80 + 443 in the Oracle VCN security list, and on the VM:
        sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 80 -j ACCEPT
        sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 443 -j ACCEPT
        sudo netfilter-persistent save
NEXT
