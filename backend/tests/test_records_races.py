import datetime as dt
import os
import tempfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "rr.db"))

from sqlmodel import Session  # noqa: E402

from app import services as S  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.integrations import orycron  # noqa: E402
from app.training import records as R  # noqa: E402

TODAY = dt.date(2026, 10, 27)


def act(date, dist, dur, splits=None, sport="running"):
    return {"date": date, "sport": sport, "distance_m": dist, "duration_s": dur, "best_efforts": splits or {}, "name": date}


def test_records_windows_and_approx():
    acts = [
        act("2025-05-01", 10000, 2700, {"1000": 250, "5000": 1300, "10000": 2700}),  # old all-time PR
        act("2026-10-10", 7200, 2100, {"1000": 249.5, "5000": 1295}),
        act("2026-09-27", 9951, 2787, {"5000": 1376}),  # no 10K split -> approx from whole run
        act("2026-10-20", 21000, 9000, sport="cycling"),
    ]
    r = R.records(acts, TODAY)
    assert r["all"]["10k"]["time_s"] == 2700 and not r["all"]["10k"]["approx"]
    assert r["6m"]["10k"]["approx"] and abs(r["6m"]["10k"]["time_s"] - 2787 * 10000 / 9951) < 1
    assert r["1m"]["5k"]["time_s"] == 1295 and r["1m"]["1k"]["time_s"] == 249.5
    assert "half" not in r["all"]  # cycling ignored


def test_predictions_models_and_consensus():
    acts = [act("2026-10-10", 7200, 2100, {"1609.344": 406, "5000": 1295})]
    p = R.predictions(acts, {"time5K": 1221, "time10K": 2601}, hr_vdot=44.0, today=TODAY)
    assert set(p["models"]) == {"vdot", "riegel", "garmin", "hr"}
    assert 45 < p["best_effort_vdot"] < 46.5  # 5K 21:35 ~ VDOT 45.6
    t10 = p["consensus"]["10k"]["seconds"]
    assert 2550 < t10 < 2800
    # Riegel 10K from 5K: 1295 * 2^1.06
    assert abs(p["models"]["riegel"]["times"]["10k"]["seconds"] - 1295 * 2 ** 1.06) < 1


def test_b_race_mini_taper_and_restore():
    init_db()
    with Session(engine) as s:
        S.update_athlete(s, vdot=44)
        S.create_plan(s, {"goal": "10k", "start_date": "2027-02-01", "days_per_week": 4, "long_run_day": 6,
                          "current_weekly_km": 35, "level": "intermediate"})
        before = {w["id"]: (w["title"], w["status"]) for w in S.list_workouts(s, "2027-02-08", "2027-02-28")}
        # Sunday of week 3 (long-run day) -> B race of 10K
        r = S.add_race(s, "Carrera B", "2027-02-21", 10000, "B")
        assert r["changes"], r
        day = S.list_workouts(s, "2027-02-21", "2027-02-21")
        assert any(w.get("race_id") == r["id"] and w["type"] == "race" for w in day)
        assert all(w["status"] == "skipped" for w in day if w.get("race_id") != r["id"] and w["sport"] == "running")
        prev = S.list_workouts(s, "2027-02-18", "2027-02-20")
        assert all(w["intensity"] == "low" for w in prev if w["sport"] == "running")
        nxt = S.list_workouts(s, "2027-02-22", "2027-02-22")
        assert all(w["type"] == "recovery" for w in nxt if w["sport"] == "running")
        S.delete_race(s, r["id"])
        after = {w["id"]: (w["title"], w["status"]) for w in S.list_workouts(s, "2027-02-08", "2027-02-28")}
        assert after == before


def test_orycron_parsers():
    page = ('<a class="btnCompeticion" href="/competiciones/52154" style="x"><div><span class="spanEstado">Inscripciones abiertas</span>'
            '<strong>12ª Carrera Popular</strong><span class="spanFecha">domingo, 1 de noviembre de 2026</span></div></a>'
            '<a class="btnCompeticion" href="/competiciones/9" style="x"><div><span class="spanEstado">Cerradas</span>'
            '<strong>Ruta BTT del Pavo</strong><span class="spanFecha">domingo, 6 de diciembre de 2026</span></div></a>')
    items = orycron.parse_listing(page)
    assert items[0] == {"external_id": "orycron:52154", "name": "12ª Carrera Popular", "date": "2026-11-01",
                        "status": "Inscripciones abiertas", "url": "https://www.orycronsport.com/competiciones/52154",
                        "running": True, "source": "orycron"}
    assert items[1]["running"] is False
    assert orycron.parse_distances_km("21,097KM - 10KM") == [21.097, 10.0]
    ev = orycron.parse_event("<p>Día:</p><p>Domingo 1 de Noviembre de 2026</p><p>Lugar:</p><p>San Esteban</p><p>Recorrido:</p><p>11,8km</p>")
    assert ev["date"] == "2026-11-01" and ev["location"] == "San Esteban" and ev["distances_km"] == [11.8]
