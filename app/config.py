from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("THEATER_CONFIG", ROOT / "config.yaml"))


def _defaults() -> dict[str, Any]:
    return {
        "app": {
            "host": "0.0.0.0",
            "port": 8080,
            "secret_key": "change-me",
            "pin": "1234",
            "public_monitor": True,
        },
        "mediamtx": {
            "api_url": "http://127.0.0.1:9997",
            "rtsp_url": "rtsp://127.0.0.1:8554/cam",
            "webrtc_url": "http://127.0.0.1:8889/cam/whep",
            "stream_path": "cam",
        },
        "capture": {
            "enabled": True,
            "source": "csi",
            "dev_mode": False,
            "video_device": "/dev/video0",
            "video_format": "",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "bitrate": 4_000_000,
            "audio_enabled": True,
            "audio_device": "default",
            "text_overlay": "%Y-%m-%d %H:%M:%S",
            "low_latency": True,
        },
        "camera": {
            "af_mode": "continuous",
            "lens_position": 0.0,
            "exposure_lock": False,
            "awb_lock": False,
            "shutter_us": 0,
            "gain": 0,
            "awb_mode": "auto",
            "ev": 0.0,
        },
        "recording": {
            "local_dir": str(ROOT / "recordings"),
            "filename_pattern": "{show}_{timestamp}",
            "default_show_name": "show",
            "container": "mp4",
            "segment_seconds": 600,
            "auto_stop_hours": 0,
            "min_free_gb": 5,
            "estimated_mbps": 8,
        },
        "sync": {
            "enabled": True,
            "smb_mount": "/mnt/theater-archive",
            "mode": "after_show",
            "interval_minutes": 30,
            "delete_local_after_sync": False,
        },
        "presets": [],
        "schedule": [],
    }


def load_config() -> dict[str, Any]:
    cfg = _defaults()
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open(encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, default_flow_style=False, sort_keys=False)


def reload_config() -> dict[str, Any]:
    global _cached
    _cached = load_config()
    return _cached


_cached: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    global _cached
    if _cached is None:
        _cached = load_config()
    return _cached


def update_config(section: str, updates: dict[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(get_config())
    if section == "root":
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    else:
        cfg.setdefault(section, {})
        cfg[section].update(updates)
    save_config(cfg)
    return reload_config()
