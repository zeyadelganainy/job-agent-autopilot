#!/usr/bin/env bash
# Push your .env + profile/ to the VM. These are gitignored and never committed (the repo
# is public). Run from the repo root on your local machine.
#   ./deploy/sync-secrets.sh ubuntu@<vm-ip> [remote-dir]
set -euo pipefail

HOST="${1:?usage: ./deploy/sync-secrets.sh user@vm-host [remote-dir]}"
DEST="${2:-job-agent-autopilot}"

[ -f .env ] || { echo "no .env here — copy .env.example to .env and fill it first"; exit 1; }
scp .env "$HOST:$DEST/.env"
scp -r profile "$HOST:$DEST/"
echo "Synced .env + profile/ to $HOST:$DEST"
echo "Apply:  ssh $HOST 'sudo systemctl restart jobagent'"
