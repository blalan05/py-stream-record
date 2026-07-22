from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.camera import (
    build_rpicam_args,
    build_usb_ffmpeg_args,
    resolve_capture_source,
    usb_ffmpeg_format_candidates,
)
from app.config import get_config

log = logging.getLogger(__name__)


@dataclass
class CaptureState:
    running: bool = False
    pid: int | None = None
    started_at: float | None = None
    last_error: str | None = None
    restarts: int = 0
    ffmpeg_cmd: str | None = None


class CaptureManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._video_proc: subprocess.Popen[bytes] | None = None
        self._ffmpeg: subprocess.Popen[bytes] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._source: str = "dev"
        self.state = CaptureState()

    def _wait_for_mediamtx(self, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        cfg = get_config()
        while time.time() < deadline:
            try:
                import httpx

                r = httpx.get(f"{cfg['mediamtx']['api_url']}/v3/paths/list", timeout=2.0)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _spawn_ffmpeg(self, cmd: list[str]) -> subprocess.Popen[bytes]:
        proc = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(proc,),
            daemon=True,
        )
        self._stderr_thread.start()
        return proc

    def _drain_stderr(self, proc: subprocess.Popen[bytes]) -> None:
        if not proc.stderr:
            return
        lines: list[str] = []
        for raw in proc.stderr:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                lines.append(line)
                log.warning("ffmpeg: %s", line)
        if proc.poll() is not None and lines:
            self.state.last_error = "\n".join(lines[-8:])

    def _read_ffmpeg_error(self, proc: subprocess.Popen[bytes]) -> str:
        if self._stderr_thread:
            self._stderr_thread.join(timeout=1.0)
        if self.state.last_error:
            return self.state.last_error
        if proc.stderr:
            try:
                err = proc.stderr.read().decode("utf-8", errors="replace").strip()
                if err:
                    return err[-2000:]
            except Exception:
                pass
        return f"ffmpeg exited {proc.returncode}"

    def _try_usb_format(
        self,
        fmt: str | None,
        *,
        force_reencode: bool = False,
    ) -> subprocess.Popen[bytes] | None:
        label = fmt or "auto"
        cmd = build_usb_ffmpeg_args(video_format=fmt, force_reencode=force_reencode)
        self.state.last_error = None
        self.state.ffmpeg_cmd = " ".join(cmd)
        log.info("USB capture trying format=%s reencode=%s: %s", label, force_reencode, self.state.ffmpeg_cmd)
        proc = self._spawn_ffmpeg(cmd)
        time.sleep(2.5)
        if proc.poll() is None:
            return proc
        proc.wait(timeout=2)
        msg = self._read_ffmpeg_error(proc)
        self.state.last_error = f"[{label}] {msg}"
        log.warning("USB capture failed format=%s: %s", label, msg)
        return None

    def _start_usb_capture(self) -> None:
        errors: list[str] = []
        for fmt in usb_ffmpeg_format_candidates():
            proc = self._try_usb_format(fmt)
            if proc:
                self._ffmpeg = proc
                return
            if self.state.last_error:
                errors.append(self.state.last_error)
            time.sleep(0.5)

        joined = " | ".join(errors) if errors else "unknown error"
        self.state.last_error = joined
        raise RuntimeError(f"USB capture failed: {joined}")

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
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-f",
            "rtsp",            "-rtsp_transport",
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
                if not self._wait_for_mediamtx():
                    raise RuntimeError("MediaMTX not ready (is mediamtx.service running?)")

                if source == "dev":
                    cmd = self._dev_ffmpeg_cmd()
                    log.info("Dev capture ffmpeg: %s", " ".join(cmd))
                    self._ffmpeg = self._spawn_ffmpeg(cmd)
                    self._video_proc = None
                elif source == "usb":
                    self._start_usb_capture()
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
            except (FileNotFoundError, RuntimeError) as exc:
                self.state.last_error = str(exc)
                log.error("Capture start failed: %s", exc)
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
        audio_enabled = cfg["capture"].get("audio_enabled", False)
        effective_device = None
        if audio_enabled:
            from app.settings import effective_audio_device

            effective_device = effective_audio_device()
        return {
            "running": self.state.running and healthy,
            "pid": self.state.pid,
            "started_at": self.state.started_at,
            "restarts": self.state.restarts,
            "last_error": self.state.last_error,
            "source": source,
            "dev_mode": source == "dev",
            "audio_enabled": audio_enabled,
            "audio_device": cfg["capture"].get("audio_device"),
            "effective_audio_device": effective_device,
            "recording_audio": audio_enabled,
            "ffmpeg_cmd": self.state.ffmpeg_cmd,            "resolution": f"{cfg['capture']['width']}x{cfg['capture']['height']}@{cfg['capture']['fps']}",
        }


capture_manager = CaptureManager()
