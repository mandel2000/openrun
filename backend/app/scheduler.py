"""In-process daily scheduler: runs the morning routine once a day at `sync_time`, or as soon as
the server is up if that time already passed (e.g. the laptop was asleep)."""

from __future__ import annotations

import datetime as dt
import logging
import threading

from sqlmodel import Session

from . import services as S
from .db import engine

log = logging.getLogger("openrun.scheduler")
_lock = threading.Lock()


def due(settings: dict, last_date: str | None, now: dt.datetime) -> bool:
    if not settings.get("auto_sync"):
        return False
    hh, mm = (int(x) for x in str(settings.get("sync_time", "06:30")).split(":"))
    return last_date != now.date().isoformat() and (now.hour, now.minute) >= (hh, mm)


def tick() -> dict | None:
    if not _lock.acquire(blocking=False):
        return None
    try:
        with Session(engine) as s:
            if due(S.get_settings(s), S.meta_get(s, "daily_log").get("last_date"), dt.datetime.now()):
                log.info("running daily routine")
                return S.daily_routine(s)
    finally:
        _lock.release()
    return None


def start(stop: threading.Event, interval_s: int = 60) -> threading.Thread:
    def loop():
        while not stop.wait(interval_s):
            try:
                tick()
            except Exception:  # noqa: BLE001 - never kill the loop
                log.exception("daily routine failed")

    t = threading.Thread(target=loop, name="openrun-scheduler", daemon=True)
    t.start()
    return t
