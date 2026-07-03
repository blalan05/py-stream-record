from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

from app.config import get_config

_CTRL_RE = re.compile(
    r"^(?P<name>\w+)\s+(?P<type>\w+)\s+"
    r"(?:min=(?P<min>-?\d+)\s+max=(?P<max>-?\d+)\s+step=(?P<step>-?\d+)\s+)?"
    r"default=(?P<default>-?\d+)\s+value=(?P<value>-?\d+)"
    r"(?:\s+flags=(?P<flags>\w+))?"
)


def _capture_device() -> str:
    return get_config()["capture"].get("video_device", "/dev/video0")


def list_v4l2_controls(device: str | None = None) -> dict[str, Any]:
    """Return V4L2 controls reported by v4l2-ctl for the capture device."""
    dev = device or _capture_device()
    if not shutil.which("v4l2-ctl"):
        return {
            "device": dev,
            "available": False,
            "error": "v4l2-ctl not installed (sudo apt install v4l-utils)",
            "controls": [],
        }

    try:
        proc = subprocess.run(
            ["v4l2-ctl", "-d", dev, "--list-ctrls"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"device": dev, "available": False, "error": str(exc), "controls": []}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return {"device": dev, "available": False, "error": err or "v4l2-ctl failed", "controls": []}

    controls: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("ioctl"):
            continue
        match = _CTRL_RE.match(line)
        if not match:
            continue
        item = match.groupdict()
        for key in ("min", "max", "step", "default", "value"):
            if item.get(key) is not None:
                item[key] = int(item[key])
        controls.append(item)

    return {
        "device": dev,
        "available": True,
        "controls": controls,
        "source": get_config()["capture"].get("source", "csi"),
    }


def set_v4l2_control(name: str, value: int | bool, device: str | None = None) -> dict[str, Any]:
    dev = device or _capture_device()
    if not shutil.which("v4l2-ctl"):
        return {"ok": False, "error": "v4l2-ctl not installed"}

    val = 1 if value is True else 0 if value is False else int(value)
    proc = subprocess.run(
        ["v4l2-ctl", "-d", dev, f"--set-ctrl={name}={val}"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return {"ok": False, "error": err or "set-ctrl failed"}
    return {"ok": True, "name": name, "value": val}


def control_groups(controls: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map common control name patterns to UI groups."""
    groups: dict[str, list[str]] = {
        "exposure": [],
        "white_balance": [],
        "focus_zoom": [],
        "image": [],
        "other": [],
    }
    patterns = {
        "exposure": ("exposure", "gain", "brightness", "backlight", "iris", "shutter"),
        "white_balance": ("white_balance", "red_balance", "blue_balance", "color"),
        "focus_zoom": ("focus", "zoom", "pan", "tilt"),
        "image": ("contrast", "saturation", "sharpness", "hue", "gamma"),
    }
    for ctrl in controls:
        name = ctrl["name"].lower()
        placed = False
        for group, keys in patterns.items():
            if any(k in name for k in keys):
                groups[group].append(ctrl["name"])
                placed = True
                break
        if not placed:
            groups["other"].append(ctrl["name"])
    return {k: v for k, v in groups.items() if v}
