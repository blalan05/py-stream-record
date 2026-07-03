from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

from urllib.parse import urlparse, urlunparse

from app.config import get_config

log = logging.getLogger(__name__)


def _cpu_temp_c() -> float | None:
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal.exists():
        try:
            return int(thermal.read_text().strip()) / 1000.0
        except (ValueError, OSError):
            return None
    return None


def disk_usage(path: str | Path | None = None) -> dict[str, Any]:
    cfg = get_config()
    target = Path(path or cfg["recording"]["local_dir"])
    target.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(target)
    return {
        "path": str(target),
        "total_gb": round(usage.total / (1024**3), 2),
        "used_gb": round(usage.used / (1024**3), 2),
        "free_gb": round(usage.free / (1024**3), 2),
        "used_percent": round(usage.used / usage.total * 100, 1),
    }


def check_disk_guard(hours: float = 3.0) -> dict[str, Any]:
    cfg = get_config()
    rec = cfg["recording"]
    disk = disk_usage()
    min_free = float(rec.get("min_free_gb", 5))
    mbps = float(rec.get("estimated_mbps", 8))
    needed_gb = (mbps * hours * 3600) / (8 * 1024) + min_free
    ok = disk["free_gb"] >= needed_gb
    return {
        "ok": ok,
        "free_gb": disk["free_gb"],
        "needed_gb": round(needed_gb, 2),
        "message": (
            f"Only {disk['free_gb']} GB free; need ~{needed_gb:.1f} GB for a {hours}h show"
            if not ok
            else "Disk space OK"
        ),
    }


def public_whep_url(request) -> str:
    """WebRTC URL reachable from the browser (not 127.0.0.1 when viewing remotely)."""
    cfg = get_config()
    configured = cfg["mediamtx"]["webrtc_url"]
    parsed = urlparse(configured)
    page_host = request.url.hostname
    port = parsed.port or 8889
    if parsed.hostname in (None, "127.0.0.1", "localhost") and page_host:
        return urlunparse(parsed._replace(netloc=f"{page_host}:{port}"))
    return configured


def mediamtx_ready() -> bool:
    cfg = get_config()
    try:
        import httpx

        r = httpx.get(f"{cfg['mediamtx']['api_url']}/v3/paths/list", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


_AUDIO_CODEC_MARKERS = (
    "audio",
    "aac",
    "opus",
    "g711",
    "mp3",
    "ac3",
    "vorbis",
    "pcm",
    "lpcm",
    "mpeg-4",
    "mpeg4",
    "mp2",
    "speex",
)


def _codec_is_audio(codec: str | None) -> bool:
    if not codec:
        return False
    lower = codec.lower()
    return any(marker in lower for marker in _AUDIO_CODEC_MARKERS)


def _normalize_path_tracks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """MediaMTX v1.11 returns codec strings; newer versions add tracks2 objects."""
    tracks: list[dict[str, Any]] = []
    for track in data.get("tracks2") or []:
        if not isinstance(track, dict):
            continue
        codec = str(track.get("codec") or "")
        tracks.append(
            {
                "type": "audio" if _codec_is_audio(codec) else "video",
                "codec": codec,
            }
        )
    if tracks:
        return tracks

    for track in data.get("tracks") or []:
        if isinstance(track, str):
            tracks.append(
                {
                    "type": "audio" if _codec_is_audio(track) else "video",
                    "codec": track,
                }
            )
        elif isinstance(track, dict):
            codec = track.get("codec") or track.get("type")
            track_type = track.get("type")
            if not track_type and codec:
                track_type = "audio" if _codec_is_audio(str(codec)) else "video"
            tracks.append(
                {
                    "type": track_type,
                    "codec": codec,
                    "id": track.get("id"),
                }
            )
    return tracks


def stream_path_info() -> dict[str, Any]:
    cfg = get_config()
    path = cfg["mediamtx"]["stream_path"]
    info: dict[str, Any] = {
        "ready": False,
        "bytes_received": 0,
        "readers": 0,
        "tracks": [],
        "ready_time": None,
    }
    try:
        import httpx

        r = httpx.get(
            f"{cfg['mediamtx']['api_url']}/v3/paths/get/{path}",
            timeout=2.0,
        )
        if r.status_code != 200:
            return info
        data = r.json()
        info["ready"] = bool(data.get("ready"))
        info["bytes_received"] = int(data.get("bytesReceived") or 0)
        info["readers"] = len(data.get("readers") or [])
        info["ready_time"] = data.get("readyTime")
        info["tracks"] = _normalize_path_tracks(data)
    except Exception:
        log.exception("Failed to read MediaMTX path info")
    return info


def stream_ready() -> bool:
    return stream_path_info()["ready"]


def stream_has_audio() -> bool:
    tracks = stream_path_info().get("tracks") or []
    return any(str(t.get("type", "")).lower() == "audio" for t in tracks)


def health_snapshot() -> dict[str, Any]:
    from app.capture import capture_manager
    from app.recorder import recorder
    from app.sync import sync_status

    stream = stream_path_info()
    return {
        "timestamp": time.time(),
        "cpu_temp_c": _cpu_temp_c(),
        "disk": disk_usage(),
        "disk_guard": check_disk_guard(),
        "capture": capture_manager.status(),
        "recording": recorder.status(),
        "mediamtx_api": mediamtx_ready(),
        "stream_ready": stream["ready"],
        "stream_has_audio": any(
            str(t.get("type", "")).lower() == "audio" for t in stream.get("tracks") or []
        ),
        "stream": stream,
        "sync": sync_status(),
    }


def prune_old_synced() -> int:
    cfg = get_config()
    if not cfg["sync"].get("delete_local_after_sync"):
        return 0
    from app.sync import _load_state

    state = _load_state()
    removed = 0
    for path_str, info in list(state.get("files", {}).items()):
        path = Path(path_str)
        if info.get("hash") and path.exists():
            path.unlink(missing_ok=True)
            removed += 1
    return removed
