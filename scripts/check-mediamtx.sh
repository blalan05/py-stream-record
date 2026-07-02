#!/usr/bin/env bash
# Quick checks when mediamtx.service fails to start.
set -u

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CONFIG="${MEDIAMTX_CONFIG:-$APP_DIR/mediamtx.yml}"
BINARY="${MEDIAMTX_BIN:-/usr/local/bin/mediamtx}"

echo "==> MediaMTX diagnostics"
echo "App dir:    $APP_DIR"
echo "Config:     $CONFIG"
echo "Binary:     $BINARY"
echo

if [[ ! -x "$BINARY" ]]; then
  echo "FAIL: mediamtx binary not found or not executable at $BINARY"
  echo "Run: sudo ./scripts/install.sh   (or set MEDIAMTX_BIN if installed elsewhere)"
  exit 1
fi
echo "OK:   binary exists"

if [[ ! -f "$CONFIG" ]]; then
  echo "FAIL: config not found at $CONFIG"
  echo "If you installed to /opt/theater-app, use: MEDIAMTX_CONFIG=/opt/theater-app/mediamtx.yml $0"
  exit 1
fi
echo "OK:   config exists"

echo
echo "==> Ports (8554 RTSP, 8889 WebRTC, 9997 API)"
if command -v ss >/dev/null 2>&1; then
  ss -tlnp 2>/dev/null | grep -E ':8554|:8889|:9997' || echo "(none in use)"
elif command -v netstat >/dev/null 2>&1; then
  netstat -tlnp 2>/dev/null | grep -E ':8554|:8889|:9997' || echo "(none in use)"
else
  echo "(ss/netstat not available)"
fi

echo
echo "==> systemd unit (if installed)"
if systemctl cat mediamtx.service >/dev/null 2>&1; then
  systemctl cat mediamtx.service | grep -E '^(ExecStart|WorkingDirectory)='
  echo
  echo "Recent service logs:"
  journalctl -u mediamtx -n 30 --no-pager 2>/dev/null || true
else
  echo "(mediamtx.service not installed)"
fi

echo
echo "==> Foreground test (5s) — actual error appears below"
echo "Command: $BINARY $CONFIG"
timeout 5 "$BINARY" "$CONFIG" 2>&1 || true
echo
echo "If you see 'address already in use', stop the process holding ports 8554/8889/9997."
echo "If you see 'no such file', fix ExecStart path in /etc/systemd/system/mediamtx.service"
