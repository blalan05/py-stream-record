from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from app.config import get_config

log = logging.getLogger(__name__)

SYNC_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "sync_state.json"
_lock = threading.Lock()


def _load_state() -> dict[str, Any]:
    if SYNC_STATE_PATH.exists():
        return json.loads(SYNC_STATE_PATH.read_text(encoding="utf-8"))
    return {"files": {}}


def _save_state(state: dict[str, Any]) -> None:
    SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _file_hash(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            data = fh.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def sync_file(path: str | Path) -> dict[str, Any]:
    cfg = get_config()
    sync_cfg = cfg["sync"]
    if not sync_cfg.get("enabled"):
        return {"path": str(path), "synced": False, "reason": "sync disabled"}

    src = Path(path)
    if not src.exists():
        return {"path": str(path), "synced": False, "reason": "missing"}

    mount = Path(sync_cfg["smb_mount"])
    if not mount.exists():
        return {"path": str(path), "synced": False, "reason": "SMB mount not available"}

    dest = mount / src.name
    digest = _file_hash(src)
    with _lock:
        state = _load_state()
        if state["files"].get(str(src), {}).get("hash") == digest and dest.exists():
            return {"path": str(path), "synced": True, "reason": "already synced"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    if _file_hash(dest) != digest:
        dest.unlink(missing_ok=True)
        return {"path": str(path), "synced": False, "reason": "hash mismatch after copy"}

    with _lock:
        state = _load_state()
        state["files"][str(src)] = {"hash": digest, "dest": str(dest), "synced_at": time.time()}
        _save_state(state)

    if sync_cfg.get("delete_local_after_sync"):
        src.unlink(missing_ok=True)

    log.info("Synced %s -> %s", src, dest)
    return {"path": str(path), "synced": True, "dest": str(dest)}


def sync_after_show(paths: list[str]) -> list[dict[str, Any]]:
    cfg = get_config()
    if cfg["sync"].get("mode") != "after_show":
        return []
    return [sync_file(p) for p in paths]


def sync_pending_local() -> list[dict[str, Any]]:
    cfg = get_config()
    local_dir = Path(cfg["recording"]["local_dir"])
    if not local_dir.exists():
        return []
    results = []
    for path in sorted(local_dir.glob("*")):
        if path.is_file() and path.suffix in {".mp4", ".ts", ".mkv"}:
            results.append(sync_file(path))
    return results


def list_recordings() -> list[dict[str, Any]]:
    cfg = get_config()
    local_dir = Path(cfg["recording"]["local_dir"])
    state = _load_state()
    items: list[dict[str, Any]] = []
    if local_dir.exists():
        for path in sorted(local_dir.glob("*"), reverse=True):
            if not path.is_file():
                continue
            info = state["files"].get(str(path), {})
            items.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
                    "synced": bool(info.get("hash")),
                    "synced_at": info.get("synced_at"),
                }
            )
    return items


def sync_status() -> dict[str, Any]:
    cfg = get_config()
    mount = Path(cfg["sync"]["smb_mount"])
    pending = [r for r in list_recordings() if not r["synced"]]
    return {
        "enabled": cfg["sync"].get("enabled", False),
        "mount": str(mount),
        "mount_available": mount.exists(),
        "mode": cfg["sync"].get("mode"),
        "pending_count": len(pending),
    }
