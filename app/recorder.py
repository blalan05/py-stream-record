from __future__ import annotations

import logging
import re
import shutil
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


def _file_has_audio(path: Path) -> bool:
    if not path.exists() or not shutil.which("ffprobe"):
        return False
    proc = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return "audio" in (proc.stdout or "")


def _recorder_ffmpeg_cmd(rtsp: str, segment_pattern: str, segment_seconds: int) -> list[str]:
    """Record video from RTSP; capture audio directly from ALSA when enabled.

    Live stream is video-only. Recordings mux RTSP video with a separate mic input.
    """
    cfg = get_config()
    ext = cfg["recording"].get("container", "mp4")
    cap = cfg["capture"]
    audio_enabled = bool(cap.get("audio_enabled"))
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        "tcp",
        "-probesize",
        "5000000",
        "-analyzeduration",
        "5000000",
        "-thread_queue_size",
        "1024",
        "-fflags",
        "+genpts+discardcorrupt",
        "-i",
        rtsp,
    ]
    if audio_enabled:
        from app.settings import effective_audio_device

        rate = int(cap.get("audio_rate") or 48000) or 48000
        channels = int(cap.get("audio_channels") or 0) or 2
        cmd.extend(
            [
                "-thread_queue_size",
                "512",
                "-f",
                "alsa",
                "-sample_fmt",
                "s16",
                "-i",
                effective_audio_device(),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-af",
                "aresample=async=1000:first_pts=0",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                str(rate),
                "-ac",
                str(channels),
            ]
        )
    else:
        cmd.extend(["-map", "0:v:0", "-c:v", "copy"])
    cmd.extend(
        [
            "-avoid_negative_ts",
            "make_zero",
            "-max_muxing_queue_size",
            "1024",
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-break_non_keyframes",
            "0",
        ]
    )
    if ext == "mp4":
        cmd.extend(
            [
                "-segment_format",
                "mp4",
                "-segment_format_options",
                "movflags=+frag_keyframe+empty_moov+default_base_moof",
            ]
        )
    cmd.append(segment_pattern)
    return cmd


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

            from app.system import check_disk_guard, stream_ready

            guard = check_disk_guard()
            if not guard["ok"]:
                raise RuntimeError(guard["message"])

            cfg = get_config()
            if not stream_ready():
                raise RuntimeError("Stream not ready — wait for capture before recording")

            show = show_name or cfg["recording"]["default_show_name"]
            local_dir, segment_pattern = self._output_path(show)
            rtsp = cfg["mediamtx"]["rtsp_url"]
            segment_seconds = int(cfg["recording"].get("segment_seconds", 600))

            cmd = _recorder_ffmpeg_cmd(rtsp, segment_pattern, segment_seconds)
            log.info("Recorder ffmpeg: %s", " ".join(cmd))
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.75)
            if proc.poll() is not None:
                err = ""
                if proc.stderr:
                    err = proc.stderr.read().decode("utf-8", errors="replace").strip()
                hint = ""
                if cfg["capture"].get("audio_enabled"):
                    hint = " Check ALSA device in Settings (plughw, not default) and test mic."
                raise RuntimeError((err or "Recording ffmpeg exited immediately") + hint)
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

        if segments and get_config()["capture"].get("audio_enabled"):
            for seg in segments[:3]:
                path = Path(seg)
                if not _file_has_audio(path):
                    log.error("Recording segment has no audio track: %s", path.name)

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
            cmd = _recorder_ffmpeg_cmd(rtsp, pattern, segment_seconds)
            self._session.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            log.warning("Recorder ffmpeg restarted mid-session")

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()


recorder = Recorder()
