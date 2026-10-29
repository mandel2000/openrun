"""Translations for text the server writes: workout titles and notes, notifications, analysis,
error messages. Strings are written in English in the code and looked up per language
(gettext style): _("Easy run") gives "Rodaje suave" for a Spanish-speaking user.

The language is the current user's (User.lang, chosen in Settings), else the request's
Accept-Language (login screen), else OPENRUN_LANG, else English. Text that is stored (a workout
title) keeps the language it was generated in.
"""

from __future__ import annotations

import os
from contextvars import ContextVar

LANGS = ("en", "es")
DEFAULT = os.environ.get("OPENRUN_LANG", "en") if os.environ.get("OPENRUN_LANG") in LANGS else "en"
_request_lang: ContextVar[str | None] = ContextVar("openrun_lang", default=None)
_user_lang: dict[int, str | None] = {}  # cache: user id -> lang


def _dict(lang: str) -> dict[str, str]:
    if lang == "es":
        from .locales.es import ES
        return ES
    return {}


def parse_accept_language(header: str | None) -> str | None:
    for part in (header or "").split(","):
        base = part.split(";")[0].strip()[:2].lower()
        if base in LANGS:
            return base
    return None


def set_request_lang(lang: str | None):
    return _request_lang.set(lang)


def reset_request_lang(token) -> None:
    _request_lang.reset(token)


def request_lang() -> str | None:
    """The browser's language for this request (Accept-Language), if supported."""
    return _request_lang.get()


def user_lang(uid: int) -> str | None:
    if uid not in _user_lang:
        from sqlmodel import Session

        from .db import User, engine

        try:
            with Session(engine) as s:
                u = s.get(User, uid)
        except Exception:  # noqa: BLE001 - no database yet (startup, tests): fall back
            return None
        if not u:
            return None
        _user_lang[uid] = u.lang
    return _user_lang[uid]


def forget_user(uid: int) -> None:
    _user_lang.pop(uid, None)


def lang() -> str:
    from .tenancy import _current

    uid = _current.get()
    return (user_lang(uid) if uid else None) or _request_lang.get() or DEFAULT


def _(text: str, **kw) -> str:
    """Translate an English string; {name} placeholders are filled from kw."""
    s = _dict(lang()).get(text, text)
    return s.format(**kw) if kw else s


def N_(text: str) -> str:
    """Mark a string for translation without translating it yet (module-level constants)."""
    return text


def language_name() -> str:
    return {"es": "Spanish", "en": "English"}[lang()]


def all_langs(text: str, **kw) -> set[str]:
    """The text in every language: for matching notes stored before a language switch."""
    out = {text.format(**kw) if kw else text}
    for code in LANGS:
        s = _dict(code).get(text)
        if s:
            out.add(s.format(**kw) if kw else s)
    return out
