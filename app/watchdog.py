from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.capture import capture_manager
from app.config import get_config
from app.recorder import recorder
from app.system import stream_ready

log = logging.getLogger(__name__)


class Watchdog:
    def __init__(self, interval: float = 5.0) -> None:
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._events: list[dict[str, Any]] = []

    def _log_event(self, kind: str, message: str) -> None:
        entry = {"kind": kind, "message": message}
        self._events.append(entry)
        self._events = self._events[-50:]
        log.warning("Watchdog: %s - %s", kind, message)

    async def _tick(self) -> None:
        cfg = get_config()
        if not cfg["capture"].get("enabled", True):
            return

        if not capture_manager.state.running:
            try:
                await asyncio.to_thread(capture_manager.start)
                self._log_event("capture_start", "Capture was down; restarted")
            except Exception as exc:
                self._log_event("capture_fail", str(exc))
        elif not capture_manager.is_healthy():
            self._log_event("capture_restart", "Capture unhealthy; restarting")
            try:
                await asyncio.to_thread(capture_manager.restart)
            except Exception as exc:
                self._log_event("capture_fail", str(exc))

        if recorder.is_recording and not recorder.status().get("recording"):
            self._log_event("recorder_restart", "Recorder ffmpeg died; restarting")
            try:
                recorder.restart_ffmpeg()
            except Exception as exc:
                self._log_event("recorder_fail", str(exc))

    async def run(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                log.exception("Watchdog tick failed")
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self.run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def recent_events(self) -> list[dict[str, Any]]:
        return list(self._events)


watchdog = Watchdog()
