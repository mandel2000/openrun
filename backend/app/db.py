from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import Column, event
from sqlalchemy.types import JSON
from sqlmodel import Field, Session, SQLModel, create_engine

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


class Athlete(SQLModel, table=True):
    id: int | None = Field(default=1, primary_key=True)
    name: str = "Atleta"
    sex: str = "male"
    age: int | None = None
    max_hr: int | None = None
    rest_hr: int | None = None
    lthr: int | None = None
    vdot: float | None = None
    vdot_source: str | None = None
    weekly_km: float | None = None


class Plan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    goal: str
    active: bool = True
    request: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class PlannedWorkout(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    plan_id: int | None = Field(default=None, index=True)
    date: str = Field(index=True)
    week: int = 0
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "planned"  # planned | done | skipped | modified
    garmin_workout_id: str | None = None
    activity_id: int | None = None
    note: str | None = None


class Activity(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    external_id: str = Field(index=True, unique=True)
    date: str = Field(index=True)
    sport: str = "running"
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    trimp: float = 0.0


class Wellness(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    date: str = Field(index=True)
    source: str = "garmin"  # garmin | zepp | ble
    hrv_rmssd: float | None = None
    rest_hr: float | None = None
    sleep_score: float | None = None
    sleep_hours: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    role: str
    content: Any = Field(sa_column=Column(JSON))


class Meta(SQLModel, table=True):
    """Small key/value store for synced blobs (Garmin predictions, PRs)."""
    key: str = Field(primary_key=True)
    value: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Race(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
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


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as s:
        yield s
