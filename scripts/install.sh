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

# MediaMTX standalone binary (RTSP/WebRTC server)
install_mediamtx() {
  if command -v mediamtx >/dev/null 2>&1; then
    echo "==> MediaMTX already installed: $(mediamtx --version 2>/dev/null | head -1 || echo mediamtx)"
    return 0
  fi

  local mtx_version="${MEDIAMTX_VERSION:-1.19.2}"
  local uname_arch mtx_arch url tmp

  uname_arch="$(uname -m)"
  case "$uname_arch" in
    aarch64|arm64)
      if [[ "$mtx_version" == 1.11.* ]]; then
        mtx_arch="arm64v8"
      else
        mtx_arch="arm64"
      fi
      ;;
    armv7l) mtx_arch="armv7" ;;
    armv6l) mtx_arch="armv6" ;;
    x86_64) mtx_arch="amd64" ;;
    *)
      echo "Unsupported CPU architecture for MediaMTX: $uname_arch"
      exit 1
      ;;
  esac

  url="https://github.com/bluenviron/mediamtx/releases/download/v${mtx_version}/mediamtx_v${mtx_version}_linux_${mtx_arch}.tar.gz"
  echo "==> Installing MediaMTX v${mtx_version} (${mtx_arch})"
  tmp="$(mktemp)"
  if ! curl -fsSL "$url" -o "$tmp"; then
    rm -f "$tmp"
    echo "FAIL: could not download MediaMTX:"
    echo "  $url"
    echo "Check MEDIAMTX_VERSION / network, or download manually from GitHub releases."
    exit 1
  fi
  sudo tar -xzf "$tmp" -C /usr/local/bin mediamtx
  rm -f "$tmp"
  sudo chmod +x /usr/local/bin/mediamtx
  echo "==> Installed: $(mediamtx --version 2>/dev/null | head -1 || echo mediamtx)"
}

install_mediamtx

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
