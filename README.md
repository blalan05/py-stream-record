# Theater Stream + Record (Raspberry Pi 5)

One Raspberry Pi 5 with a Camera Module 3 can **stream live video to monitors** (browser/WebRTC) and **record archival copies** to local storage, then auto-sync them to a Windows/SMB share on your network.

Replaces:
- Phone streaming to monitors
- Hard-to-reach SD-card archival camera

## Hardware

| Item | Recommendation |
|------|----------------|
| Computer | Raspberry Pi 5 (8 GB recommended) |
| Camera | USB webcam (recommended) or Pi Camera Module 3 (CSI ribbon) |
| Storage | NVMe HAT or USB SSD for recording buffer |
| Network | Wired Ethernet on the Pi |
| Audio | USB audio interface with line-in from sound board (best) or USB mic |

## Architecture

```
USB camera + USB audio
        │
        ▼
  ffmpeg (V4L2)  ──publish──▶  MediaMTX (WebRTC + RTSP)
        │                                    │
        │                                    ├──▶ Monitors (browser /monitor)
        │                                    └──▶ ffmpeg recorder (stream copy, segmented MP4)
        │                                              │
        │                                              ▼
        │                                        Local SSD
        │                                              │
        └────────────────────────────────── auto-sync ──▶ SMB share (PC/NAS)
```

## Web UI

| URL | Purpose |
|-----|---------|
| `http://<pi-ip>:8080/` | Operator dashboard (PIN protected) |
| `http://<pi-ip>:8080/monitor` | Fullscreen monitor view (public on LAN by default) |
| `http://<pi-ip>:8080/recordings` | Browse/download/sync recordings |
| `http://<pi-ip>:8080/settings` | Recording + capture settings |
| `http://<pi-ip>:8080/schedule` | Auto start/stop by showtime |

Default PIN: `1234` — change in `config.yaml` before production.

### Dashboard features

- Live WebRTC preview
- **Start Show** — apply preset, verify stream, start recording
- Manual record start/stop with show name
- Exposure / white-balance lock and scene presets
- Disk space, CPU temp, sync status

## Install on Raspberry Pi

1. Flash **Raspberry Pi OS Bookworm 64-bit**.
2. Plug in the USB camera. For CSI modules only: `sudo raspi-config` → Interface Options → Camera.
3. Clone/copy this project to the Pi.
4. Edit `config.yaml` (PIN, recording path, SMB mount, audio device, **video source**).
5. Run:

```bash
chmod +x scripts/install.sh scripts/mount-share.sh
sudo ./scripts/install.sh
```

6. Mount your archive share:

```bash
# Create /etc/theater-app/smb.credentials first (see scripts/mount-share.sh)
sudo ./scripts/mount-share.sh //YOUR-PC/theater-archive /mnt/theater-archive
```

7. Open `http://<pi-ip>:8080` and log in.

After changing code in your clone (e.g. `~/py-stream-record`), deploy to the running install:

```bash
chmod +x scripts/deploy.sh
sudo ./scripts/deploy.sh              # default target: /opt/theater-app
sudo ./scripts/deploy.sh ~/py-stream-record   # if install lives in your home dir
```

Services:
```bash
sudo systemctl status mediamtx theater-app
sudo journalctl -u mediamtx -n 50 --no-pager
sudo journalctl -u theater-app -f
```

If `mediamtx.service` shows **Failed** / **start request repeated too quickly**, run the diagnostic script from your project folder:

```bash
chmod +x scripts/check-mediamtx.sh
./scripts/check-mediamtx.sh
```

That runs MediaMTX in the foreground briefly and prints the actual error (systemd often hides it).

**Common fixes:**
- **Config path mismatch** — the unit expects `/opt/theater-app/mediamtx.yml`. If you run from `~/py-stream-record`, reinstall with:
  ```bash
  sudo INSTALL_DIR="$HOME/py-stream-record" ./scripts/install.sh
  ```
  Or copy `mediamtx.yml` to wherever `systemctl cat mediamtx.service` points.
- **Unknown config fields** — `mediamtx.yml` must match the installed binary (currently **v1.11.3**). Do not use newer docs field names like `webrtcAllowOrigins` (plural) or per-path `writeQueueSize`.
- **Binary missing** — same install script downloads MediaMTX to `/usr/local/bin/mediamtx`
- **Port in use** — `sudo ss -tlnp | grep -E '8554|8889|9997'` then stop the conflicting process

## USB camera setup

List V4L2 devices on the Pi:

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
```

In `config.yaml` (or **Settings → Video source**):

```yaml
capture:
  source: usb
  video_device: "/dev/video0"
  video_format: ""          # optional: mjpeg, h264, yuyv422, etc.
  width: 1920
  height: 1080
  fps: 30
```

Use the `/dev/video*` node that lists capture formats (often `video0`, not `video1`). If ffmpeg fails to open the device, try setting `video_format` to one of the formats from `v4l2-ctl --list-formats-ext`. Match width/height/fps to a mode your camera actually supports.

**HDMI USB capture (H.264 only)** — many dongles expose only `H264`. Example:

```yaml
capture:
  source: usb
  video_device: "/dev/video0"
  video_format: h264
  width: 1920
  height: 1080
  fps: 30
  text_overlay: ""   # passthrough can't burn in timestamps without re-encode
```

The app passes H.264 through without re-encoding on the Pi (`-c:v copy`), which keeps CPU low at 1080p.

Dashboard exposure/focus controls apply only to the Pi CSI camera (`source: csi`).

## Audio setup

List ALSA devices on the Pi:

```bash
arecord -l
```

Set the device in **Settings → Audio device**, e.g. `plughw:2,0` for a USB interface.

For archival quality, use a **line-level feed from your sound board** into a USB audio interface — not the camera mic.

## Development (PC, no Pi camera)

Set in `config.yaml`:

```yaml
capture:
  dev_mode: true
```

Install and run:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

`dev_mode` uses an ffmpeg test pattern + tone published to MediaMTX. You still need MediaMTX and ffmpeg installed locally.

## Configuration

**Browser (Settings page):** video source (CSI / USB / dev), USB device path, resolution, fps, bitrate, audio device, recording folder, SMB path, sync mode, segment length, auto-stop hours.

**Files (advanced):**
- `config.yaml` — app settings (production copy at `/etc/theater-app/config.yaml`)
- `mediamtx.yml` — WebRTC/RTSP tuning for MediaMTX **v1.11.3** (`writeQueueSize`, ports). Config field names must match the installed binary version.

## Operating a show

1. Power on Pi; services start automatically.
2. Open dashboard on a phone/laptop on theater Wi‑Fi.
3. Adjust camera preset if needed (exposure lock helps with stage lighting).
4. Tap **Start Show**, enter show name.
5. Open `/monitor` on each display (bookmark or kiosk mode).
6. After the show, tap **Stop** — files sync to the network share.

## Troubleshooting

| Issue | Check |
|-------|-------|
| MediaMTX won't start | `chmod +x scripts/check-mediamtx.sh && ./scripts/check-mediamtx.sh` — shows the real error. Common: wrong config path in systemd (`/opt/theater-app` vs your clone), missing binary, or ports 8554/8889/9997 already in use |
| No preview | `systemctl status mediamtx`; is capture running on dashboard? For USB: `v4l2-ctl --list-devices`, check `video_device` in config |
| Stream not ready | Wait a few seconds after boot; check `journalctl -u theater-app` |
| No audio | `arecord -l`, verify device in Settings, restart capture |
| Disk full | Dashboard disk guard; free space or enable delete-after-sync |
| SMB sync fails | Is `/mnt/theater-archive` mounted? Run sync manually on Recordings page |

## License

MIT
