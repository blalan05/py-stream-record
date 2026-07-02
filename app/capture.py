from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.camera import build_rpicam_args, build_usb_ffmpeg_args, resolve_capture_source
from app.config import get_config

log = logging.getLogger(__name__)


@dataclass
class CaptureState:
    running: bool = False
    pid: int | None = None
    started_at: float | None = None
    last_error: str | None = None
    restarts: int = 0


class CaptureManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._video_proc: subprocess.Popen[bytes] | None = None
        self._ffmpeg: subprocess.Popen[bytes] | None = None
        self._source: str = "dev"
        self.state = CaptureState()

    def _dev_ffmpeg_cmd(self) -> list[str]:
        cfg = get_config()
        cap = cfg["capture"]
        rtsp = cfg["mediamtx"]["rtsp_url"]
        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-re",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={cap['width']}x{cap['height']}:rate={cap['fps']}",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            rtsp,
        ]

    def _pi_pipeline_cmd(self) -> tuple[list[str], list[str]]:
        cfg = get_config()
        rtsp = cfg["mediamtx"]["rtsp_url"]
        rpicam = build_rpicam_args()
        ffmpeg = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            "pipe:0",
            "-c",
            "copy",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            rtsp,
        ]
        return rpicam, ffmpeg

    def start(self) -> None:
        with self._lock:
            if self.state.running:
                return
            cfg = get_config()
            if not cfg["capture"].get("enabled", True):
                log.info("Capture disabled in config")
                return
            try:
                source = resolve_capture_source()
                self._source = source
                if not shutil.which("ffmpeg"):
                    raise FileNotFoundError("ffmpeg not found")

                if source == "dev":
                    self._ffmpeg = subprocess.Popen(self._dev_ffmpeg_cmd())
                    self._video_proc = None
                elif source == "usb":
                    self._ffmpeg = subprocess.Popen(build_usb_ffmpeg_args())
                    self._video_proc = None
                else:
                    rpicam_cmd, ffmpeg_cmd = self._pi_pipeline_cmd()
                    self._video_proc = subprocess.Popen(
                        rpicam_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    self._ffmpeg = subprocess.Popen(
                        ffmpeg_cmd,
                        stdin=self._video_proc.stdout,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    if self._video_proc.stdout:
                        self._video_proc.stdout.close()
                self.state.running = True
                self.state.pid = self._ffmpeg.pid if self._ffmpeg else None
                self.state.started_at = time.time()
                self.state.last_error = None
                log.info("Capture started (source=%s, pid=%s)", source, self.state.pid)
            except FileNotFoundError as exc:
                self.state.last_error = str(exc)
                log.error("Capture binary missing: %s", exc)
                raise

    def stop(self) -> None:
        with self._lock:
            for proc in (self._ffmpeg, self._video_proc):
                if proc and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            self._ffmpeg = None
            self._video_proc = None
            self.state.running = False
            self.state.pid = None

    def restart(self) -> None:
        self.stop()
        time.sleep(0.5)
        self.start()
        self.state.restarts += 1

    def is_healthy(self) -> bool:
        if not self.state.running:
            return False
        if self._ffmpeg and self._ffmpeg.poll() is not None:
            err = self._ffmpeg.stderr.read().decode("utf-8", errors="replace") if self._ffmpeg.stderr else ""
            self.state.last_error = err or f"ffmpeg exited {self._ffmpeg.returncode}"
            self.state.running = False
            return False
        if self._video_proc and self._video_proc.poll() is not None:
            err = (
                self._video_proc.stderr.read().decode("utf-8", errors="replace")
                if self._video_proc.stderr
                else ""
            )
            self.state.last_error = err or f"rpicam-vid exited {self._video_proc.returncode}"
            self.state.running = False
            return False
        return True

    def status(self) -> dict[str, Any]:
        healthy = self.is_healthy()
        cfg = get_config()
        source = resolve_capture_source()
        return {
            "running": self.state.running and healthy,
            "pid": self.state.pid,
            "started_at": self.state.started_at,
            "restarts": self.state.restarts,
            "last_error": self.state.last_error,
            "source": source,
            "dev_mode": source == "dev",
            "audio_enabled": cfg["capture"].get("audio_enabled", False),
            "resolution": f"{cfg['capture']['width']}x{cfg['capture']['height']}@{cfg['capture']['fps']}",
        }


capture_manager = CaptureManager()
