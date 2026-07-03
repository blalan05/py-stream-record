#!/usr/bin/env bash
# Sync local project changes to the installed app directory and restart services.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${1:-${INSTALL_DIR:-/opt/theater-app}}"

if [[ ! -d "$INSTALL_DIR" ]]; then
  echo "Install dir not found: $INSTALL_DIR"
  echo "Run: sudo INSTALL_DIR=\"\$HOME/py-stream-record\" ./scripts/install.sh"
  exit 1
fi

echo "==> Deploy $SRC_DIR -> $INSTALL_DIR"

sudo rsync -a \
  --exclude .venv \
  --exclude recordings \
  --exclude data \
  --exclude .git \
  "$SRC_DIR/" "$INSTALL_DIR/"

echo "==> Restart services"
sudo systemctl restart mediamtx theater-app

sleep 2
sudo systemctl is-active mediamtx theater-app
echo "==> Done. UI: http://$(hostname -I | awk '{print $1}'):8080"
