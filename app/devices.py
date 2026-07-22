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
_ARECORD_CARD_RE = re.compile(
    r"^card\s+(\d+):\s*(.+?),\s*device\s+(\d+):\s*(.+)$",
    re.IGNORECASE,
)


def _parse_arecord_line(line: str) -> dict[str, Any] | None:
    match = _ARECORD_CARD_RE.match(line.strip())
    if not match:
        return None
    card = match.group(1)
    card_desc = match.group(2).strip()
    device = match.group(3)
    device_desc = match.group(4).strip()
    card_name = card_desc.split("[", 1)[0].strip() or card_desc
    device_name = device_desc.split("[", 1)[0].strip() or device_desc
    alsa = f"plughw:{card},{device}"
    return {
        "alsa": alsa,
        "name": f"{card_name} — {device_name} ({alsa})",
        "card": int(card),
        "device": int(device),
    }


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
    hardware: list[dict[str, Any]] = []

    if not shutil.which("arecord"):
        return {
            "available": False,
            "error": "arecord not installed (sudo apt install alsa-utils)",
            "devices": [{"alsa": "default", "name": "System default"}],
            "recommended": "default",
        }

    proc = _run(["arecord", "-l"])
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return {
            "available": False,
            "error": err or "arecord failed",
            "devices": [{"alsa": "default", "name": "System default"}],
            "recommended": "default",
        }

    for line in proc.stdout.splitlines():
        item = _parse_arecord_line(line)
        if item:
            hardware.append(item)

    devices = hardware + [
        {
            "alsa": "default",
            "name": "System default (often fails on Pi — prefer plughw above)",
        }
    ]
    recommended = hardware[0]["alsa"] if hardware else "default"
    return {"available": True, "devices": devices, "recommended": recommended}


def _friendly_alsa_error(device: str, output: str, returncode: int, busy_hint: str | None = None) -> str:
    if busy_hint:
        return busy_hint
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    tail = "; ".join(lines[-2:]) if lines else f"ffmpeg exited {returncode}"
    lower = tail.lower()
    if "busy" in lower or "input/output error" in lower:
        return (
            f"{tail}. The device may be in use (capture holds it when audio is enabled). "
            "Uncheck Audio enabled, save, then test mic — or use the dashboard audio meter while streaming."
        )
    if device == "default":
        info = list_audio_devices()
        suggested = info.get("recommended")
        if suggested and suggested != "default":
            return (
                f"{tail}. On Raspberry Pi, 'default' usually fails — "
                f"select '{suggested}' from the dropdown instead."
            )
    return tail


def _capture_using_device(device: str) -> str | None:
    """Return a user message if the recorder already has this ALSA device open."""
    try:
        from app.recorder import recorder
        from app.config import get_config
        from app.settings import effective_audio_device

        cfg = get_config()
        if not cfg["capture"].get("audio_enabled") or not recorder.is_recording:
            return None
        active = effective_audio_device()
        candidates = {device, active, cfg["capture"].get("audio_device", "")}
        normalized = {c.replace("plughw:", "hw:") for c in candidates if c}
        if device.replace("plughw:", "hw:") in normalized or device in candidates:
            return (
                "This mic is in use by the active recording. Stop recording first, then test mic."
            )
    except Exception:
        pass
    return None


def _arecord_probe(device: str, seconds: float = 1.0, sample_rate: int = 0) -> tuple[bool, str]:
    cmd = ["arecord", "-D", device, "-d", str(max(1, int(seconds))), "-f", "S16_LE", "-t", "raw", "-q"]
    if sample_rate > 0:
        cmd.extend(["-r", str(sample_rate)])
    cmd.append("/dev/null")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 8, check=False)
    except subprocess.TimeoutExpired:
        return False, "arecord timed out"
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or "").strip()


def _ffmpeg_volumedetect(
    device: str,
    duration: float,
    sample_rate: int,
    channels: int,
) -> dict[str, Any]:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-f", "alsa"]
    if sample_rate > 0:
        cmd.extend(["-ar", str(sample_rate)])
    if channels > 0:
        cmd.extend(["-ac", str(channels)])
    cmd.extend(["-i", device, "-t", str(duration), "-af", "volumedetect", "-f", "null", "-"])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 15, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Mic test timed out", "device": device}

    output = (proc.stderr or "") + (proc.stdout or "")
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": _friendly_alsa_error(device, output, proc.returncode),
            "device": device,
        }

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


def test_audio_device(
    device: str,
    duration: float = 2.0,
    sample_rate: int = 0,
    channels: int = 0,
) -> dict[str, Any]:
    """Capture briefly and report volume levels via ffmpeg volumedetect."""
    busy = _capture_using_device(device)
    if busy:
        return {"ok": False, "error": busy, "device": device, "busy": True}

    if not shutil.which("ffmpeg"):
        return {"ok": False, "error": "ffmpeg not found"}

    # Try device-native settings first, then configured rate/channels.
    attempts: list[tuple[int, int]] = [(0, 0)]
    if sample_rate > 0 or channels > 0:
        attempts.append((sample_rate, channels))

    last_error = "Could not open audio device"
    for rate, ch in attempts:
        ok, err = _arecord_probe(device, seconds=1.0, sample_rate=rate)
        if not ok:
            last_error = err or last_error
            continue
        result = _ffmpeg_volumedetect(device, duration, rate, ch)
        if result.get("ok"):
            if rate == 0 and (sample_rate > 0 or channels > 0):
                result["message"] = (
                    f"{result.get('message', 'OK')} "
                    f"(device native rate; saved setting {sample_rate or 'auto'} Hz also works)"
                )
            return result
        last_error = result.get("error", last_error)

    return {
        "ok": False,
        "error": _friendly_alsa_error(device, last_error, 1, busy_hint=busy),
        "device": device,
    }
