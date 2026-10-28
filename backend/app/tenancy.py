"""Per-user data isolation.

Every row of the athlete's data carries `user_id`. The current user lives in a context variable set
by the auth middleware (web requests) or `as_user()` (scheduler, background jobs, MCP). Two ORM
hooks make the rest of the code multi-user without threading a user id through every query:

- SELECTs on tenant tables get `WHERE user_id = <current>` added automatically.
- New tenant rows get `user_id = <current>` on flush.

Without a current user, touching tenant tables raises: data never leaks across accounts by accident.
Code that really needs every user's rows (migrations, admin) passes execution option `all_users=True`.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.orm import Session as _OrmSession
from sqlalchemy.orm import with_loader_criteria

_current: ContextVar[int | None] = ContextVar("openrun_user", default=None)
TENANT_MODELS: list[type] = []


class NoUserContext(RuntimeError):
    pass


def tenant(cls):
    """Class decorator for tables whose rows belong to one user."""
    TENANT_MODELS.append(cls)
    return cls


def current_user_id() -> int:
    uid = _current.get()
    if uid is None:
        raise NoUserContext("Sin usuario en contexto")
    return uid


def set_user(uid: int | None):
    return _current.set(uid)


def reset_user(token) -> None:
    _current.reset(token)


@contextlib.contextmanager
def as_user(uid: int):
    tok = _current.set(uid)
    try:
        yield
    finally:
        _current.reset(tok)


@event.listens_for(_OrmSession, "do_orm_execute")
def _filter_by_user(state) -> None:
    if not state.is_select or state.execution_options.get("all_users"):
        return
    if state.is_column_load or state.is_relationship_load:
        return
    uid = _current.get()
    touched = {m.entity for m in state.all_mappers} if hasattr(state, "all_mappers") else set()
    tenants = [m for m in TENANT_MODELS if m in touched] or ([] if touched else TENANT_MODELS)
    if not tenants:
        return
    if uid is None:
        raise NoUserContext("Consulta de datos sin usuario en contexto")
    for m in tenants:
        state.statement = state.statement.options(
            with_loader_criteria(m, m.user_id == uid, include_aliases=True))


@event.listens_for(_OrmSession, "before_flush")
def _stamp_user(session, _ctx, _instances) -> None:
    for obj in session.new:
        if type(obj) in TENANT_MODELS and getattr(obj, "user_id", None) is None:
            obj.user_id = current_user_id()
