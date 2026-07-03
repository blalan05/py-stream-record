#!/usr/bin/env bash
# List V4L2 controls for the capture device (what can be adjusted programmatically).
set -u

DEVICE="${1:-/dev/video0}"

echo "==> Device: $DEVICE"
echo

if ! command -v v4l2-ctl >/dev/null 2>&1; then
  echo "Install v4l-utils: sudo apt install v4l-utils"
  exit 1
fi

echo "==> Supported formats"
v4l2-ctl -d "$DEVICE" --list-formats-ext 2>/dev/null || true

echo
echo "==> Adjustable controls (programmatic settings)"
v4l2-ctl -d "$DEVICE" --list-ctrls 2>/dev/null || echo "(none or device not found)"

echo
echo "==> Current values"
v4l2-ctl -d "$DEVICE" --get-ctrl=all 2>/dev/null | head -40 || true

echo
echo "In the app (after deploy): GET /api/camera/controls (login required)"
