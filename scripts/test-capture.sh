#!/usr/bin/env bash
# Find a working USB camera format and test RTSP publish to MediaMTX.
set -u

DEVICE="${1:-/dev/video0}"
SIZE="${CAPTURE_SIZE:-1280x720}"
FPS="${CAPTURE_FPS:-30}"
RTSP="${RTSP_URL:-rtsp://127.0.0.1:8554/cam}"
API="${MEDIAMTX_API:-http://127.0.0.1:9997}"

probe_format() {
  local fmt="$1"
  local extra=()
  [[ -n "$fmt" ]] && extra=(-input_format "$fmt")
  timeout 5 ffmpeg -hide_banner -loglevel error -f v4l2 "${extra[@]}" \
    -video_size "$SIZE" -framerate "$FPS" -i "$DEVICE" -an -f null -
}

echo "==> V4L2 devices"
v4l2-ctl --list-devices 2>/dev/null || echo "(install v4l-utils: sudo apt install v4l-utils)"
echo
echo "==> Formats on $DEVICE"
v4l2-ctl -d "$DEVICE" --list-formats-ext 2>/dev/null || echo "Cannot read $DEVICE"

echo
echo "==> MediaMTX path (before)"
curl -s "$API/v3/paths/get/cam" 2>/dev/null || echo "MediaMTX API not reachable"
echo

echo "==> Stopping theater-app (frees the camera)"
sudo systemctl stop theater-app 2>/dev/null || true
sleep 1

WORKING_FMT=""
for fmt in h264 mjpeg ""; do
  label="${fmt:-auto}"
  echo
  echo "==> Probe format: $label"
  if probe_format "$fmt" 2>&1; then
    echo "OK: $label"
    WORKING_FMT="$fmt"
    break
  fi
  echo "FAIL: $label"
done

if [[ "$WORKING_FMT" == "" ]] && ! probe_format "" >/dev/null 2>&1; then
  echo
  echo "FAIL: No working format on $DEVICE at $SIZE@${FPS}fps"
  sudo systemctl start theater-app 2>/dev/null || true
  exit 1
fi

echo
echo "==> Publish test (10s) using format: ${WORKING_FMT:-auto}"
extra=()
[[ -n "$WORKING_FMT" ]] && extra=(-input_format "$WORKING_FMT")
if [[ "$WORKING_FMT" == "h264" ]]; then
  encode=(-c:v copy -bsf:v h264_mp4toannexb)
else
  encode=(-c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p)
fi

timeout 12 ffmpeg -hide_banner -loglevel warning -f v4l2 "${extra[@]}" \
  -video_size "$SIZE" -framerate "$FPS" -i "$DEVICE" -an \
  "${encode[@]}" -f rtsp -rtsp_transport tcp "$RTSP" &
sleep 3
echo "==> MediaMTX path (during publish)"
curl -s "$API/v3/paths/get/cam"
echo
wait || true

echo
echo "==> Restart theater-app"
sudo systemctl start theater-app 2>/dev/null || true
if [[ -n "$WORKING_FMT" ]]; then
  echo "Set in /etc/theater-app/config.yaml: capture.video_format: $WORKING_FMT"
else
  echo 'Set in /etc/theater-app/config.yaml: capture.video_format: ""'
fi
echo "  capture.video_device: $DEVICE"
