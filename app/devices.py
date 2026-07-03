from __future__ import annotations

import logging
import re
import shutil
import subprocess
from typing import Any

log = logging.getLogger(__name__)

_DEVICE_HEADER_RE = re.compile(r"^(.+?):\s*$")
_DEVICE_PATH_RE = re.compile(r"^\s*(/dev/video\d+)\s*$")
_FORMAT_RE = re.compile(r"^\s*\[\d+\]:\s+'([^']+)'")
_SIZE_RE = re.compile(r"^\s*Size:\s+Discrete\s+(\d+)x(\d+)")
_FPS_RE = re.compile(r"^\s*Interval:\s+(?:Discrete|Continuous)\s+[\d.s]+\s*\(([\d.]+)\s*fps\)")
_ARECORD_CARD_RE = re.compile(r"^card (\d+): (.+?) \[(.+?)\], device (\d+): (.+?) \[(.+?)\]")


def _run(cmd: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _parse_formats_ext(output: str) -> list[dict[str, Any]]:
    formats: list[dict[str, Any]] = []
    current_format: dict[str, Any] | None = None
    current_resolution: dict[str, Any] | None = None

    for line in output.splitlines():
        fmt_match = _FORMAT_RE.match(line)
        if fmt_match:
            current_format = {"format": fmt_match.group(1).lower(), "resolutions": []}
            formats.append(current_format)
            current_resolution = None
            continue

        size_match = _SIZE_RE.match(line)
        if size_match and current_format is not None:
            current_resolution = {
                "width": int(size_match.group(1)),
                "height": int(size_match.group(2)),
                "fps": [],
            }
            current_format["resolutions"].append(current_resolution)
            continue

        fps_match = _FPS_RE.match(line)
        if fps_match and current_resolution is not None:
            fps = float(fps_match.group(1))
            if fps == int(fps):
                fps = int(fps)
            if fps not in current_resolution["fps"]:
                current_resolution["fps"].append(fps)

    return formats


def probe_video_device(device_path: str) -> dict[str, Any] | None:
    """Return device info for a single V4L2 path (fallback when list-devices parsing fails)."""
    if not shutil.which("v4l2-ctl"):
        return None
    fmt_proc = _run(["v4l2-ctl", "-d", device_path, "--list-formats-ext"], timeout=15)
    if fmt_proc.returncode != 0:
        return None
    formats = _parse_formats_ext(fmt_proc.stdout)
    if not formats:
        return None
    return {"device": device_path, "name": device_path, "formats": formats}


def list_video_devices() -> dict[str, Any]:
    """Return V4L2 capture devices with supported formats and resolutions."""
    if not shutil.which("v4l2-ctl"):
        return {
            "available": False,
            "error": "v4l2-ctl not installed (sudo apt install v4l-utils)",
            "devices": [],
        }

    proc = _run(["v4l2-ctl", "--list-devices"])
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return {"available": False, "error": err or "v4l2-ctl failed", "devices": []}

    devices: list[dict[str, Any]] = []
    seen: set[str] = set()
    current_name: str | None = None

    for line in proc.stdout.splitlines():
        header = _DEVICE_HEADER_RE.match(line.strip())
        if header and not line.startswith("\t") and not line.startswith(" "):
            current_name = header.group(1).strip()
            continue

        path_match = _DEVICE_PATH_RE.match(line)
        if not path_match or not current_name:
            continue

        device_path = path_match.group(1)
        if device_path in seen:
            continue
        seen.add(device_path)

        fmt_proc = _run(["v4l2-ctl", "-d", device_path, "--list-formats-ext"], timeout=15)
        if fmt_proc.returncode != 0:
            continue
        formats = _parse_formats_ext(fmt_proc.stdout)
        if not formats:
            continue
        devices.append(
            {
                "device": device_path,
                "name": current_name,
                "formats": formats,
            }
        )

    return {"available": True, "devices": devices}


def list_audio_devices() -> dict[str, Any]:
    """Return ALSA capture devices suitable for ffmpeg -f alsa."""
    devices: list[dict[str, Any]] = [{"alsa": "default", "name": "System default"}]

    if not shutil.which("arecord"):
        return {
            "available": False,
            "error": "arecord not installed (sudo apt install alsa-utils)",
            "devices": devices,
        }

    proc = _run(["arecord", "-l"])
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return {"available": False, "error": err or "arecord failed", "devices": devices}

    for line in proc.stdout.splitlines():
        match = _ARECORD_CARD_RE.match(line.strip())
        if not match:
            continue
        card = match.group(1)
        card_name = match.group(2)
        device = match.group(4)
        device_name = match.group(5)
        alsa = f"plughw:{card},{device}"
        devices.append(
            {
                "alsa": alsa,
                "name": f"{card_name} — {device_name} ({alsa})",
                "card": int(card),
                "device": int(device),
            }
        )

    return {"available": True, "devices": devices}


def test_audio_device(device: str, duration: float = 2.0) -> dict[str, Any]:
    """Capture briefly and report volume levels via ffmpeg volumedetect."""
    if not shutil.which("ffmpeg"):
        return {"ok": False, "error": "ffmpeg not found"}

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "info",
        "-f",
        "alsa",
        "-i",
        device,
        "-t",
        str(duration),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Mic test timed out"}

    output = (proc.stderr or "") + (proc.stdout or "")
    if proc.returncode != 0:
        tail = output.strip().splitlines()[-3:]
        return {"ok": False, "error": "; ".join(tail) or f"ffmpeg exited {proc.returncode}"}

    mean_volume: float | None = None
    max_volume: float | None = None
    for line in output.splitlines():
        if "mean_volume:" in line:
            try:
                mean_volume = float(line.split("mean_volume:")[1].split("dB")[0].strip())
            except ValueError:
                pass
        if "max_volume:" in line:
            try:
                max_volume = float(line.split("max_volume:")[1].split("dB")[0].strip())
            except ValueError:
                pass

    signal = mean_volume is not None and mean_volume > -50.0
    return {
        "ok": True,
        "device": device,
        "mean_volume_db": mean_volume,
        "max_volume_db": max_volume,
        "signal_detected": signal,
        "message": (
            "Signal detected — mic looks good"
            if signal
            else "Very quiet or silent — check device and input gain"
        ),
    }
