from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import Column, event
from sqlalchemy.types import JSON
from sqlmodel import Field, Session, SQLModel, create_engine

from .tenancy import tenant

# SQLite file by default (single user, zero ops). OPENRUN_DATABASE_URL switches to e.g. Postgres:
#   postgresql+psycopg://user:pass@host:5432/openrun
DB_URL = os.getenv("OPENRUN_DATABASE_URL", "")
DB_PATH = Path(os.getenv("OPENRUN_DB", Path.home() / ".openrun" / "openrun.db"))
if DB_URL:
    engine = create_engine(DB_URL, pool_pre_ping=True)
else:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(conn, _):  # WAL: the daily routine thread and web requests don't block each other
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    name: str = ""
    password_hash: str = ""
    is_admin: bool = False
    created_at: str = ""


class Invite(SQLModel, table=True):
    code: str = Field(primary_key=True)
    created_by: int
    created_at: str
    expires_at: str
    used_by: int | None = None
    note: str | None = None


class PushSubscription(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    endpoint: str = Field(unique=True)
    keys: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: str = ""


@tenant
class Athlete(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True, unique=True)
    name: str = "Atleta"
    sex: str = "male"
    age: int | None = None
    max_hr: int | None = None
    rest_hr: int | None = None
    lthr: int | None = None
    vdot: float | None = None
    vdot_source: str | None = None
    weekly_km: float | None = None
    weight_kg: float | None = None


@tenant
class Plan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    name: str
    goal: str
    active: bool = True
    request: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


@tenant
class PlannedWorkout(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    plan_id: int | None = Field(default=None, index=True)
    date: str = Field(index=True)
    week: int = 0
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "planned"  # planned | done | skipped | modified
    garmin_workout_id: str | None = None
    activity_id: int | None = None
    note: str | None = None


@tenant
class Activity(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    external_id: str = Field(index=True)
    date: str = Field(index=True)
    sport: str = "running"
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    trimp: float = 0.0


@tenant
class Wellness(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    date: str = Field(index=True)
    source: str = "garmin"  # garmin | zepp | ble
    hrv_rmssd: float | None = None
    rest_hr: float | None = None
    sleep_score: float | None = None
    sleep_hours: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


@tenant
class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    role: str
    content: Any = Field(sa_column=Column(JSON))


@tenant
class Meta(SQLModel, table=True):
    """Small per-user key/value store (settings, synced blobs, logs)."""
    user_id: int | None = Field(default=None, primary_key=True)
    key: str = Field(primary_key=True)
    value: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


@tenant
class Race(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    name: str
    date: str = Field(index=True)
    distance_m: float | None = None
    priority: str = "B"  # A = objetivo, B = preparatoria (mini-taper), C = entreno
    location: str | None = None
    url: str | None = None
    source: str = "manual"  # manual | orycron
    external_id: str | None = None
    goal_time_s: float | None = None
    result_time_s: float | None = None
    notes: str | None = None
    course: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # uploaded GPX profile
    strategy: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # chosen target, start time


TENANT_TABLES = ["athlete", "plan", "plannedworkout", "activity", "wellness", "chatmessage", "meta", "race"]


def _migrate_single_user() -> None:
    """Pre-multi-user SQLite databases: rebuild each data table with `user_id` (all rows -> user 1).
    Rebuilding (instead of ALTER) also drops the old unique/PK constraints that are now per user.
    Runs as ONE transaction on a raw connection (SQLite DDL is transactional; pysqlite's implicit
    commits are disabled) after a full file backup, so a failure leaves the database untouched."""
    import sqlite3

    from sqlalchemy.schema import CreateIndex, CreateTable

    con = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        def cols(t: str) -> list[str]:
            return [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]

        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        old = [t for t in TENANT_TABLES if t in have and "user_id" not in cols(t)]
        if not old:
            return
        backup = DB_PATH.with_name(DB_PATH.stem + "-pre-multiuser.db")
        if not backup.exists():
            dest = sqlite3.connect(backup)
            con.backup(dest)
            dest.close()
        con.execute("BEGIN IMMEDIATE")
        try:
            for t in old:
                for (idx,) in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (t,)).fetchall():
                    con.execute(f'DROP INDEX "{idx}"')
                con.execute(f'ALTER TABLE "{t}" RENAME TO "{t}__old"')
                table = SQLModel.metadata.tables[t]
                con.execute(str(CreateTable(table).compile(engine)))
                for ix in table.indexes:
                    con.execute(str(CreateIndex(ix).compile(engine)))
                keep = [x for x in cols(f"{t}__old") if x in set(cols(t)) and x != "user_id"]
                sel = ", ".join(f'"{x}"' for x in keep)
                con.execute(f'INSERT INTO "{t}" ({sel}, user_id) SELECT {sel}, 1 FROM "{t}__old"')
                con.execute(f'DROP TABLE "{t}__old"')
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def _add_missing_columns() -> None:
    """New nullable columns on existing tables (create_all only creates missing tables)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as c:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {col["name"] for col in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    c.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'))


def init_db() -> None:
    if not DB_URL:
        _migrate_single_user()
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def get_session():
    with Session(engine) as s:
        yield s
