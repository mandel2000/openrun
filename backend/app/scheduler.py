"""In-process daily scheduler: runs the morning routine once a day at `sync_time`, or as soon as
the server is up if that time already passed (e.g. the laptop was asleep)."""

from __future__ import annotations

import datetime as dt
import logging
import threading

from sqlmodel import Session, select

from . import services as S
from .db import User, engine
from .tenancy import as_user

log = logging.getLogger("openrun.scheduler")
_lock = threading.Lock()
STATE: dict = {"running": False, "last_tick": None, "last_backup": None, "backup_error": None}


def due(settings: dict, last_date: str | None, now: dt.datetime) -> bool:
    if not settings.get("auto_sync"):
        return False
    hh, mm = (int(x) for x in str(settings.get("sync_time", "06:30")).split(":"))
    return last_date != now.date().isoformat() and (now.hour, now.minute) >= (hh, mm)


def user_ids() -> list[int]:
    with Session(engine) as s:
        return [u.id for u in s.exec(select(User).order_by(User.id)).all()]


def tick() -> dict | None:
    """Run the daily routine for every user that is due; returns {user_id: log} (None if busy)."""
    if not _lock.acquire(blocking=False):
        return None
    out: dict = {}
    try:
        for uid in user_ids():
            try:
                with as_user(uid), Session(engine) as s:
                    if due(S.get_settings(s), S.meta_get(s, "daily_log").get("last_date"), dt.datetime.now()):
                        log.info("running daily routine for user %s", uid)
                        out[uid] = S.daily_routine(s)
            except Exception:  # noqa: BLE001 - one user's failure must not stop the others
                log.exception("daily routine failed for user %s", uid)
        if out or _backup_due():
            try:
                S.backup_db()
                STATE.update(last_backup=dt.datetime.now().isoformat(timespec="seconds"), backup_error=None)
            except Exception as e:  # noqa: BLE001
                log.exception("backup failed")
                if STATE.get("backup_error") is None:
                    _alert_admins("Copia de seguridad fallida", f"La copia diaria de OpenRun ha fallado: {e}")
                STATE["backup_error"] = str(e)
        _hourly(out)
        STATE["last_tick"] = dt.datetime.now().isoformat(timespec="seconds")
    finally:
        _lock.release()
    return out


def _alert_admins(title: str, body: str) -> None:
    """Push to every admin's devices (operational problems only the server owner can fix)."""
    from . import push

    with Session(engine) as s:
        admins = [u.id for u in s.exec(select(User).where(User.is_admin == True)).all()]  # noqa: E712
    for uid in admins:
        try:
            push.send(uid, title, body, "/#ajustes", "ops")
        except Exception:  # noqa: BLE001
            log.warning("admin alert failed", exc_info=True)


_last_backup: list[str] = []


def _backup_due() -> bool:
    today = dt.date.today().isoformat()
    if _last_backup and _last_backup[0] == today:
        return False
    _last_backup[:] = [today]
    return True


_last_intraday: dict[int, float] = {}
INTRADAY_EVERY_S = 2 * 3600


def intraday(_ran: dict) -> None:
    """Every ~2 h between 9:00 and 22:00: pick up new runs, analyse and notify them."""
    import time

    now = dt.datetime.now()
    if not 9 <= now.hour < 22:
        return
    for uid in user_ids():
        if time.time() - _last_intraday.get(uid, 0) < INTRADAY_EVERY_S:
            continue
        _last_intraday[uid] = time.time()
        try:
            with as_user(uid), Session(engine) as s:
                if S.get_settings(s).get("auto_sync"):
                    S.intraday_sync(s)
        except Exception:  # noqa: BLE001
            log.exception("intraday sync failed for user %s", uid)


_HOOKS: list = [intraday]  # extra per-tick jobs; each gets the routines that ran


def _hourly(ran: dict) -> None:
    for fn in _HOOKS:
        try:
            fn(ran)
        except Exception:  # noqa: BLE001
            log.exception("scheduler hook failed")


def start(stop: threading.Event, interval_s: int = 60) -> threading.Thread:
    def loop():
        while not stop.wait(interval_s):
            try:
                tick()
            except Exception:  # noqa: BLE001 - never kill the loop
                log.exception("daily routine failed")

    t = threading.Thread(target=loop, name="openrun-scheduler", daemon=True)
    t.start()
    STATE.update(running=True, started=dt.datetime.now().isoformat(timespec="seconds"), interval_s=interval_s)
    return t
