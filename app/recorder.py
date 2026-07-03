from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_config

log = logging.getLogger(__name__)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip()) or "show"


@dataclass
class RecordingSession:
    show_name: str
    started_at: float
    output_pattern: str
    segment_dir: Path
    process: subprocess.Popen[bytes] | None = None
    segments: list[str] = field(default_factory=list)


class Recorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: RecordingSession | None = None
        self._auto_stop_timer: threading.Timer | None = None

    def _alive_locked(self) -> bool:
        """Return whether the recorder ffmpeg process is running (lock must be held)."""
        if not self._session or not self._session.process:
            return False
        return self._session.process.poll() is None

    def _status_locked(self) -> dict[str, Any]:
        """Build status dict (lock must be held)."""
        if not self._session:
            return {"recording": False}
        elapsed = time.time() - self._session.started_at
        return {
            "recording": self._alive_locked(),
            "show_name": self._session.show_name,
            "started_at": self._session.started_at,
            "elapsed_seconds": int(elapsed),
            "output_pattern": self._session.output_pattern,
        }

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._alive_locked()

    def _output_path(self, show_name: str) -> tuple[Path, str]:
        cfg = get_config()
        rec = cfg["recording"]
        local_dir = Path(rec["local_dir"])
        local_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        show = _slug(show_name or rec["default_show_name"])
        pattern = rec["filename_pattern"].format(show=show, timestamp=ts)
        ext = rec.get("container", "mp4")
        segment_pattern = str(local_dir / f"{pattern}_%03d.{ext}")
        return local_dir, segment_pattern

    def start(self, show_name: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._alive_locked():
                raise RuntimeError("Already recording")

            from app.system import check_disk_guard

            guard = check_disk_guard()
            if not guard["ok"]:
                raise RuntimeError(guard["message"])

            cfg = get_config()
            show = show_name or cfg["recording"]["default_show_name"]
            local_dir, segment_pattern = self._output_path(show)
            rtsp = cfg["mediamtx"]["rtsp_url"]
            segment_seconds = int(cfg["recording"].get("segment_seconds", 600))

            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-rtsp_transport",
                "tcp",
                "-i",
                rtsp,
                "-c",
                "copy",
                "-f",
                "segment",
                "-segment_time",
                str(segment_seconds),
                "-reset_timestamps",
                "1",
                "-strftime",
                "0",
                segment_pattern,
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._session = RecordingSession(
                show_name=show,
                started_at=time.time(),
                output_pattern=segment_pattern,
                segment_dir=local_dir,
                process=proc,
            )
            self._schedule_auto_stop()
            log.info("Recording started: %s", segment_pattern)
            return self._status_locked()

    def _schedule_auto_stop(self) -> None:
        cfg = get_config()
        hours = float(cfg["recording"].get("auto_stop_hours") or 0)
        if hours <= 0:
            return
        if self._auto_stop_timer:
            self._auto_stop_timer.cancel()

        def _stop() -> None:
            try:
                self.stop()
            except Exception:
                log.exception("Auto-stop failed")

        self._auto_stop_timer = threading.Timer(hours * 3600, _stop)
        self._auto_stop_timer.daemon = True
        self._auto_stop_timer.start()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._session:
                return self._status_locked()
            proc = self._session.process
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            pattern = self._session.output_pattern
            segment_dir = self._session.segment_dir
            self._session = None
            if self._auto_stop_timer:
                self._auto_stop_timer.cancel()
                self._auto_stop_timer = None

        segments = sorted(str(p) for p in segment_dir.glob(Path(pattern).name.replace("%03d", "*")))
        log.info("Recording stopped, %d segments", len(segments))

        def _sync_background() -> None:
            from app.sync import sync_after_show

            try:
                sync_after_show(segments)
            except Exception:
                log.exception("Background sync after show failed")

        threading.Thread(target=_sync_background, daemon=True).start()
        return self.status()

    def restart_ffmpeg(self) -> None:
        """Restart recorder ffmpeg without ending session metadata."""
        with self._lock:
            if not self._session or not self._session.process:
                return
            show = self._session.show_name
            pattern = self._session.output_pattern
            proc = self._session.process
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            cfg = get_config()
            rtsp = cfg["mediamtx"]["rtsp_url"]
            segment_seconds = int(cfg["recording"].get("segment_seconds", 600))
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-rtsp_transport",
                "tcp",
                "-i",
                rtsp,
                "-c",
                "copy",
                "-f",
                "segment",
                "-segment_time",
                str(segment_seconds),
                "-reset_timestamps",
                "1",
                "-strftime",
                "0",
                pattern,
            ]
            self._session.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            log.warning("Recorder ffmpeg restarted mid-session")

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()


recorder = Recorder()
