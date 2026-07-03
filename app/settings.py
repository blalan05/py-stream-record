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


def save_preset(
    name: str,
    camera: dict[str, Any] | None = None,
    v4l2: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    presets = list_presets()
    entry: dict[str, Any] = {"name": name}
    if camera is not None:
        entry["camera"] = camera
    if v4l2 is not None:
        entry["v4l2"] = v4l2
    for idx, preset in enumerate(presets):
        if preset["name"] == name:
            if "camera" not in entry and "camera" in preset:
                entry["camera"] = preset["camera"]
            if "v4l2" not in entry and "v4l2" in preset:
                entry["v4l2"] = preset["v4l2"]
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
        if preset["name"] != name:
            continue
        cfg = get_config()
        source = cfg["capture"].get("source", "csi")
        if source == "usb" and preset.get("v4l2"):
            from app.v4l2_controls import apply_v4l2_controls

            return {"kind": "v4l2", **apply_v4l2_controls(preset["v4l2"])}
        if preset.get("camera"):
            return {"kind": "csi", "camera": update_camera_settings(preset["camera"])}
        raise KeyError(f"Preset {name} has no settings for source {source}")
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


def rotation_video_filters() -> list[str]:
    """ffmpeg -vf filters for capture.rotation / capture.rotation_fine."""
    cap = get_config()["capture"]
    parts: list[str] = []
    rotation = int(cap.get("rotation") or 0) % 360
    if rotation == 90:
        parts.append("transpose=1")
    elif rotation == 180:
        parts.append("transpose=2,transpose=2")
    elif rotation == 270:
        parts.append("transpose=2")

    fine = float(cap.get("rotation_fine") or 0)
    if abs(fine) > 0.01:
        radians = fine * 3.141592653589793 / 180.0
        parts.append(f"rotate={radians}:c=none")

    return parts


def rotation_video_filter() -> str | None:
    filters = rotation_video_filters()
    return ",".join(filters) if filters else None


def capture_needs_reencode() -> bool:
    cap = get_config()["capture"]
    return bool(rotation_video_filters()) or bool(cap.get("text_overlay"))


def build_usb_ffmpeg_args(video_format: str | None = None) -> list[str]:
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
    if video_format is None:
        fmt = (cap.get("video_format") or "").strip().lower()
    else:
        fmt = video_format.strip().lower()
    if cap.get("low_latency"):
        args.extend(["-fflags", "nobuffer"])
    if fmt:
        args.extend(["-input_format", fmt])
    needs_reencode = capture_needs_reencode() or bool(fmt != "h264")
    if fmt == "h264" and not needs_reencode:
        args.extend(["-use_wallclock_as_timestamps", "1"])
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
    vf_parts.extend(rotation_video_filters())
    if cap.get("text_overlay"):
        overlay = cap["text_overlay"].replace("'", r"'\''")
        vf_parts.append(
            f"drawtext=expansion=strftime:text='{overlay}'"
            ":x=10:y=10:fontsize=24:fontcolor=white:box=1:boxcolor=0x00000080"
        )

    if vf_parts:
        args.extend(["-vf", ",".join(vf_parts)])

    args.extend(["-map", "0:v"])
    if cap.get("audio_enabled"):
        args.extend(["-map", "1:a?"])

    if fmt == "h264" and not vf_parts:
        args.extend(["-c:v", "copy", "-bsf:v", "h264_mp4toannexb"])
    else:
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
        args.extend(["-c:a", "aac"])
    else:
        args.append("-an")
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


def usb_ffmpeg_format_candidates() -> list[str]:
    """Try configured format first, then common USB camera formats."""
    cap = get_config()["capture"]
    configured = (cap.get("video_format") or "").strip().lower()
    candidates: list[str] = []

    if capture_needs_reencode():
        # MJPEG decodes more reliably for rotate/overlay re-encode on the Pi.
        for fmt in (configured, "mjpeg", "h264", ""):
            if fmt and fmt not in candidates:
                candidates.append(fmt)
        if "" not in candidates:
            candidates.append("")
        return candidates

    if configured:
        candidates.append(configured)
    for fmt in ("h264", "mjpeg", ""):
        if fmt not in candidates:
            candidates.append(fmt)
    return candidates


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
    if cap.get("ev"):
        args.extend(["--ev", str(cam["ev"])])
    rotation = int(get_config()["capture"].get("rotation") or 0)
    if rotation in (90, 180, 270):
        args.extend(["--rotation", str(rotation)])

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
