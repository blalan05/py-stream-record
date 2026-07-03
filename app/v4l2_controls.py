from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

from app.config import get_config

_LINE_RE = re.compile(
    r"^\s*(?P<name>\w+)\s+0x[0-9a-fA-F]+\s+\((?P<type>\w+)\)\s*:\s*(?P<attrs>.+)$"
)
_ATTR_RE = re.compile(r"(\w+)=(-?\d+)")

_GROUP_ORDER = (
    ("exposure", ("exposure", "gain", "brightness", "backlight", "iris", "shutter")),
    ("white_balance", ("white_balance", "power_line", "color_temp")),
    ("focus_zoom", ("focus", "zoom", "pan", "tilt")),
    ("image", ("contrast", "saturation", "sharpness", "hue", "gamma")),
)


def _capture_device() -> str:
    return get_config()["capture"].get("video_device", "/dev/video0")


def _parse_control_line(line: str) -> dict[str, Any] | None:
    match = _LINE_RE.match(line)
    if not match:
        return None
    item: dict[str, Any] = {
        "name": match.group("name"),
        "type": match.group("type"),
    }
    attrs = match.group("attrs")
    for attr_match in _ATTR_RE.finditer(attrs):
        key = attr_match.group(1)
        if key in ("min", "max", "step", "default", "value"):
            item[key] = int(attr_match.group(2))
    item["inactive"] = "inactive" in attrs
    item["label"] = item["name"].replace("_", " ")
    return item


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
        item = _parse_control_line(line)
        if item:
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
        return {"ok": False, "error": err or "set-ctrl failed", "name": name}
    return {"ok": True, "name": name, "value": val}


def apply_v4l2_controls(controls: dict[str, Any], device: str | None = None) -> dict[str, Any]:
    """Apply multiple V4L2 controls. Order matters for auto/manual pairs."""
    ordered_names = [
        "white_balance_automatic",
        "auto_exposure",
    ]
    remaining = {k: v for k, v in controls.items()}
    applied: dict[str, Any] = {}
    errors: list[str] = []

    for name in ordered_names:
        if name in remaining:
            result = set_v4l2_control(name, remaining.pop(name), device)
            if result.get("ok"):
                applied[name] = result["value"]
            else:
                errors.append(f"{name}: {result.get('error', 'failed')}")

    for name, value in remaining.items():
        result = set_v4l2_control(name, value, device)
        if result.get("ok"):
            applied[name] = result["value"]
        else:
            errors.append(f"{name}: {result.get('error', 'failed')}")

    refreshed = list_v4l2_controls(device)
    return {
        "ok": not errors,
        "applied": applied,
        "errors": errors,
        "controls": refreshed.get("controls", []),
    }


def control_groups(controls: list[dict[str, Any]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {key: [] for key, _ in _GROUP_ORDER}
    groups["other"] = []
    for ctrl in controls:
        name = ctrl["name"].lower()
        placed = False
        for group, keys in _GROUP_ORDER:
            if any(k in name for k in keys):
                groups[group].append(ctrl["name"])
                placed = True
                break
        if not placed:
            groups["other"].append(ctrl["name"])
    return {k: v for k, v in groups.items() if v}


def controls_as_dict(controls: list[dict[str, Any]]) -> dict[str, int]:
    return {c["name"]: c.get("value", c.get("default", 0)) for c in controls if "value" in c or "default" in c}
