from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from app.config import get_config, reload_config, save_config
from app.recorder import recorder

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def list_schedule() -> list[dict[str, Any]]:
    return list(get_config().get("schedule", []))


def save_schedule(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cfg = reload_config()
    cfg["schedule"] = entries
    save_config(cfg)
    reload_config()
    _register_jobs()
    return entries


def add_schedule_entry(
    show_name: str,
    start_at: str,
    stop_at: str,
) -> list[dict[str, Any]]:
    entries = list_schedule()
    entry = {
        "id": str(uuid.uuid4()),
        "show_name": show_name,
        "start_at": start_at,
        "stop_at": stop_at,
    }
    entries.append(entry)
    return save_schedule(entries)


def delete_schedule_entry(entry_id: str) -> list[dict[str, Any]]:
    entries = [e for e in list_schedule() if e.get("id") != entry_id]
    return save_schedule(entries)


async def _job_start(show_name: str) -> None:
    log.info("Scheduled start: %s", show_name)
    if not recorder.is_recording:
        recorder.start(show_name)


async def _job_stop() -> None:
    log.info("Scheduled stop")
    if recorder.is_recording:
        recorder.stop()


def _register_jobs() -> None:
    scheduler.remove_all_jobs()
    for entry in list_schedule():
        job_id = entry["id"]
        try:
            start_dt = _parse_dt(entry["start_at"])
            stop_dt = _parse_dt(entry["stop_at"])
        except ValueError:
            log.warning("Invalid schedule entry: %s", entry)
            continue
        scheduler.add_job(
            _job_start,
            DateTrigger(run_date=start_dt),
            args=[entry.get("show_name", "show")],
            id=f"{job_id}-start",
            replace_existing=True,
        )
        scheduler.add_job(
            _job_stop,
            DateTrigger(run_date=stop_dt),
            id=f"{job_id}-stop",
            replace_existing=True,
        )


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
    _register_jobs()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
