# Deploying JobPilot always-on (Oracle Cloud Always Free)
A single always-on VM runs the console **and** the daily agent for $0.

1. Create an **Always Free Ubuntu** VM with a public IP. Open ingress for ports **80** and **443**
   in the VCN security list, **and** on the VM open the host firewall (Oracle's Ubuntu image blocks
   everything but SSH by default):
   ```bash
   sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```
2. Point a free [DuckDNS](https://www.duckdns.org) subdomain at the VM's public IP.
3. On the VM: `git clone … && cd job-agent-autopilot && bash deploy/install.sh`
   (installs Caddy + `uv`, then a managed **Python 3.11** venv and the dependencies).
4. From your laptop: `./deploy/sync-secrets.sh ubuntu@<vm-ip>` to push `.env` + `profile/`
   (these stay out of the public repo).
5. Edit `deploy/Caddyfile` with your domain, then `sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy`.
6. `sudo cp deploy/jobagent.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now jobagent`.

Caddy provisions automatic HTTPS; the console sits behind a login page (a session cookie signed with
`SESSION_SECRET`, falling back to `WEB_PASSWORD`; HTTP Basic is also accepted); use a strong
password. The agent's daily run fires from the always-on service and emails you.

**Updating a deployment:** `git pull && uv pip install --python .venv/bin/python -r requirements.txt
&& sudo systemctl restart jobagent`, then re-run `sync-secrets.sh` if your `.env`/profile changed.
