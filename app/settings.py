from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import ROOT, get_config, reload_config, save_config

log = logging.getLogger(__name__)

PRESETS_PATH = ROOT / "data" / "presets.json"


def _ensure_presets_file() -> None:
    PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PRESETS_PATH.exists():
        PRESETS_PATH.write_text("[]", encoding="utf-8")


def list_presets() -> list[dict[str, Any]]:
    _ensure_presets_file()
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))


def save_preset(name: str, camera: dict[str, Any]) -> list[dict[str, Any]]:
    presets = list_presets()
    entry = {"name": name, "camera": camera}
    for idx, preset in enumerate(presets):
        if preset["name"] == name:
            presets[idx] = entry
            break
    else:
        presets.append(entry)
    PRESETS_PATH.write_text(json.dumps(presets, indent=2), encoding="utf-8")
    cfg = reload_config()
    cfg["presets"] = presets
    save_config(cfg)
    return presets


def delete_preset(name: str) -> list[dict[str, Any]]:
    presets = [p for p in list_presets() if p["name"] != name]
    PRESETS_PATH.write_text(json.dumps(presets, indent=2), encoding="utf-8")
    cfg = reload_config()
    cfg["presets"] = presets
    save_config(cfg)
    return presets


def get_camera_settings() -> dict[str, Any]:
    return dict(get_config()["camera"])


def update_camera_settings(updates: dict[str, Any]) -> dict[str, Any]:
    from app.config import update_config

    return update_config("camera", updates)


def apply_preset(name: str) -> dict[str, Any]:
    for preset in list_presets():
        if preset["name"] == name:
            return update_camera_settings(preset["camera"])
    raise KeyError(f"Preset not found: {name}")


def resolve_capture_source() -> str:
    """Return effective capture source: csi, usb, or dev."""
    import shutil

    cfg = get_config()
    cap = cfg["capture"]
    if cap.get("dev_mode"):
        return "dev"
    source = cap.get("source", "csi")
    if source == "csi" and not shutil.which("rpicam-vid"):
        log.warning("rpicam-vid not found; falling back to dev test pattern")
        return "dev"
    return source


def build_usb_ffmpeg_args() -> list[str]:
    cfg = get_config()
    cap = cfg["capture"]
    rtsp = cfg["mediamtx"]["rtsp_url"]
    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "v4l2",
    ]
    fmt = (cap.get("video_format") or "").strip()
    if fmt:
        args.extend(["-input_format", fmt])
    args.extend(
        [
            "-video_size",
            f"{cap['width']}x{cap['height']}",
            "-framerate",
            str(cap["fps"]),
            "-i",
            cap.get("video_device", "/dev/video0"),
        ]
    )
    if cap.get("audio_enabled"):
        args.extend(["-f", "alsa", "-i", cap.get("audio_device", "default")])

    vf_parts: list[str] = []
    if cap.get("text_overlay"):
        overlay = cap["text_overlay"].replace("'", r"'\''")
        vf_parts.append(
            f"drawtext=expansion=strftime:text='{overlay}'"
            ":x=10:y=10:fontsize=24:fontcolor=white:box=1:boxcolor=0x00000080"
        )
    if vf_parts:
        args.extend(["-vf", ",".join(vf_parts)])

    args.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            str(cap["bitrate"]),
        ]
    )
    if cap.get("audio_enabled"):
        args.extend(["-c:a", "aac", "-shortest"])
    args.extend(
        [
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            rtsp,
        ]
    )
    return args


def build_rpicam_args() -> list[str]:
    cfg = get_config()
    cap = cfg["capture"]
    cam = cfg["camera"]
    args = [
        "rpicam-vid",
        "--codec",
        "libav",
        "--libav-format",
        "mpegts",
        "--width",
        str(cap["width"]),
        "--height",
        str(cap["height"]),
        "--framerate",
        str(cap["fps"]),
        "--bitrate",
        str(cap["bitrate"]),
        "--inline",
        "-t",
        "0",
        "-o",
        "-",
    ]
    if cap.get("text_overlay"):
        args.extend(["--datetime", cap["text_overlay"]])
    if cap.get("low_latency"):
        args.append("--low-latency")
    if cap.get("audio_enabled"):
        args.extend(["--libav-audio", "--audio-device", cap.get("audio_device", "default")])

    af_mode = cam.get("af_mode", "continuous")
    if af_mode:
        args.extend(["--autofocus-mode", af_mode])
    lens = cam.get("lens_position")
    if lens is not None and af_mode in ("manual", "fixed"):
        args.extend(["--lens-position", str(lens)])

    if cam.get("exposure_lock"):
        if cam.get("shutter_us"):
            args.extend(["--shutter", str(cam["shutter_us"])])
        if cam.get("gain"):
            args.extend(["--gain", str(cam["gain"])])
    if cam.get("awb_lock") and cam.get("awb_mode"):
        args.extend(["--awb", cam["awb_mode"]])
    if cam.get("ev"):
        args.extend(["--ev", str(cam["ev"])])

    return args


def get_editable_settings() -> dict[str, Any]:
    cfg = get_config()
    return {
        "capture": cfg["capture"],
        "recording": cfg["recording"],
        "sync": cfg["sync"],
        "camera": cfg["camera"],
    }


def save_editable_settings(payload: dict[str, Any]) -> dict[str, Any]:
    from app.config import update_config

    for section in ("capture", "recording", "sync", "camera"):
        if section in payload:
            update_config(section, payload[section])
    return get_editable_settings()
