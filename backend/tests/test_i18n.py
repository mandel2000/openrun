import os
import tempfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "i18n.db"))
os.environ["OPENRUN_SCHEDULER"] = "0"

import re  # noqa: E402

from sqlmodel import Session  # noqa: E402

from app import i18n  # noqa: E402
from app.db import User, engine, init_db  # noqa: E402
from app.i18n import _  # noqa: E402
from app.locales.es import ES  # noqa: E402
from app.tenancy import as_user  # noqa: E402
from app.training import strength  # noqa: E402
from app.training import workouts as W  # noqa: E402
from app.training.vdot import training_paces  # noqa: E402


def _user(lang):
    init_db()
    with Session(engine) as s:
        u = User(username=f"u-{lang}", lang=lang)
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def test_english_by_default_and_spanish_per_user():
    init_db()
    paces = training_paces(45)
    assert W.easy_run(paces, 8).title == "Easy run 8 km"
    with as_user(_user("es")):
        assert W.easy_run(paces, 8).title == "Rodaje suave 8 km"
        assert strength.session("base")["exercises"][0]["name"] == "Sentadilla goblet"
    with as_user(_user("en")):
        assert strength.session("base")["title"] == "General strength"


def test_request_language_when_no_user():
    tok = i18n.set_request_lang(i18n.parse_accept_language("es-ES,es;q=0.9,en;q=0.8"))
    try:
        assert _("Please sign in") == "Inicia sesión"
    finally:
        i18n.reset_request_lang(tok)
    assert i18n.parse_accept_language("fr-FR, de") is None


def test_spanish_entries_keep_placeholders():
    """A translation must use exactly the placeholders of its English key, or .format() breaks."""
    ph = lambda t: sorted(re.findall(r"\{(\w+)\}", t))  # noqa: E731
    bad = [k for k, v in ES.items() if ph(k) != ph(v)]
    assert bad == []


def test_every_server_string_has_a_spanish_entry():
    """Each _("...") / N_("...") literal in app/ needs an entry in app/locales/es.py."""
    import ast
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "app"
    used = set()
    for f in app.rglob("*.py"):
        if "locales" in f.parts:
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("_", "N_")
                    and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                used.add(n.args[0].value)
    assert sorted(u for u in used if u not in ES) == []


def test_sign_in_message_follows_browser_language():
    from fastapi.testclient import TestClient

    from app import main

    c = TestClient(main.app, client=("203.0.113.5", 5000))
    assert c.get("/api/athlete", headers={"Accept-Language": "es-ES"}).json()["detail"] == "Inicia sesión"
    assert c.get("/api/athlete", headers={"Accept-Language": "en"}).json()["detail"] == "Please sign in"
