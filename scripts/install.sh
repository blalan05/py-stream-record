#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/theater-app}"
RECORD_DIR="${RECORD_DIR:-/var/lib/theater-app/recordings}"
VENV_DIR="$INSTALL_DIR/.venv"

echo "==> Theater app install -> $INSTALL_DIR"

sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  ffmpeg \
  gstreamer1.0-tools gstreamer1.0-plugins-good \
  cifs-utils \
  curl

# MediaMTX (arm64 Pi)
if ! command -v mediamtx >/dev/null 2>&1; then
  ARCH="$(uname -m)"
  case "$ARCH" in
    aarch64|arm64) MTX_ARCH="arm64" ;;
    armv7l|armv6l) MTX_ARCH="arm32v7" ;;
    x86_64) MTX_ARCH="amd64" ;;
    *) echo "Unsupported arch: $ARCH"; exit 1 ;;
  esac
  MTX_VERSION="1.11.3"
  curl -fsSL "https://github.com/bluenviron/mediamtx/releases/download/v${MTX_VERSION}/mediamtx_v${MTX_VERSION}_linux_${MTX_ARCH}.tar.gz" \
    | sudo tar -xz -C /usr/local/bin mediamtx
fi

sudo mkdir -p "$INSTALL_DIR" "$RECORD_DIR" /etc/theater-app
sudo rsync -a --exclude .venv --exclude recordings --exclude data "$APP_DIR/" "$INSTALL_DIR/"

if [[ ! -f /etc/theater-app/config.yaml ]]; then
  sudo cp "$INSTALL_DIR/config.yaml" /etc/theater-app/config.yaml
  sudo sed -i "s|local_dir:.*|local_dir: \"$RECORD_DIR\"|" /etc/theater-app/config.yaml
fi

sudo python3 -m venv "$VENV_DIR"
sudo "$VENV_DIR/bin/pip" install --upgrade pip
sudo "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

sudo cp "$INSTALL_DIR/systemd/mediamtx.service" /etc/systemd/system/
sudo cp "$INSTALL_DIR/systemd/theater-app.service" /etc/systemd/system/
sudo sed -i "s|/opt/theater-app|$INSTALL_DIR|g" /etc/systemd/system/mediamtx.service
sudo sed -i "s|/opt/theater-app|$INSTALL_DIR|g" /etc/systemd/system/theater-app.service

sudo systemctl daemon-reload
sudo systemctl enable mediamtx theater-app
sudo systemctl restart mediamtx
sleep 2
sudo systemctl restart theater-app

echo "==> Done."
echo "Control UI: http://$(hostname -I | awk '{print $1}'):8080"
echo "Monitor:    http://$(hostname -I | awk '{print $1}'):8080/monitor"
echo "Default PIN is in /etc/theater-app/config.yaml (change it!)"
