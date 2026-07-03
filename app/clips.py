from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from app.config import get_config

log = logging.getLogger(__name__)

CLIPS_SUBDIR = "clips"


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip()) or "clip"


def _local_root() -> Path:
    return Path(get_config()["recording"]["local_dir"]).resolve()


def _clips_dir() -> Path:
    path = _local_root() / CLIPS_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_recording_path(path: str | Path) -> Path:
    """Ensure path is an existing file under the recording local_dir."""
    local_root = _local_root()
    resolved = Path(path).resolve()
    if local_root not in resolved.parents and resolved.parent != local_root:
        raise ValueError("Invalid path")
    if not resolved.exists() or not resolved.is_file():
        raise ValueError("File not found")
    return resolved


def list_clips() -> list[dict[str, Any]]:
    clips_dir = _clips_dir()
    items: list[dict[str, Any]] = []
    for path in sorted(clips_dir.glob("*.mp4"), reverse=True):
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
            }
        )
    return items


def create_clip(source_path: str | Path, start_s: float, end_s: float, name: str) -> dict[str, Any]:
    src = validate_recording_path(source_path)
    if end_s <= start_s:
        raise ValueError("End time must be after start time")
    if end_s - start_s < 0.5:
        raise ValueError("Clip must be at least 0.5 seconds")

    slug = _slug(name)
    out = _clips_dir() / f"{slug}.mp4"
    if out.exists():
        raise ValueError(f"Clip already exists: {out.name}")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(start_s),
        "-to",
        str(end_s),
        "-i",
        str(src),
        "-c",
        "copy",
        "-y",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or f"ffmpeg exited {proc.returncode}")

    log.info("Created clip %s from %s (%.1f-%.1fs)", out, src, start_s, end_s)
    return {
        "name": out.name,
        "path": str(out),
        "size_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "start_s": start_s,
        "end_s": end_s,
    }


def delete_clip(path: str | Path) -> dict[str, Any]:
    clips_dir = _clips_dir()
    resolved = Path(path).resolve()
    if clips_dir not in resolved.parents:
        raise ValueError("Invalid clip path")
    if not resolved.exists():
        raise ValueError("Clip not found")
    resolved.unlink(missing_ok=True)
    return {"deleted": str(resolved)}
