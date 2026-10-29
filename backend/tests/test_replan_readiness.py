import datetime as dt
import os
import tempfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "auto.db"))
os.environ["OPENRUN_SCHEDULER"] = "0"

from sqlmodel import Session  # noqa: E402

from app import services as S  # noqa: E402
from app.db import Activity, PlannedWorkout, User, engine, init_db  # noqa: E402
from app.tenancy import as_user  # noqa: E402
from app.training import load, replan  # noqa: E402

init_db()
TODAY = dt.date.today()


def day(n: int) -> str:
    return (TODAY + dt.timedelta(days=n)).isoformat()


def new_user(name: str, admin: bool = False) -> int:
    with Session(engine) as s:
        u = User(username=name, is_admin=admin)
        s.add(u)
        s.commit()
        return u.id


def run(title: str, date: str, typ: str = "easy", inten: str = "low", km: float = 8) -> PlannedWorkout:
    return PlannedWorkout(date=date, data={"title": title, "sport": "running", "type": typ, "intensity": inten,
                                           "distance_km": km, "steps": [], "date": date})


def test_readiness_score_combines_parts():
    rows = [{"date": (TODAY - dt.timedelta(days=30 - i)).isoformat(), "hrv_rmssd": 60 + (i % 3), "rest_hr": 48} for i in range(30)]
    good = load.readiness(rows + [{"date": TODAY.isoformat(), "sleep_score": 85, "feel": 4, "legs": 4}], TODAY, {"tsb": 2, "acwr": 1.0})
    assert good.status == "green" and good.score >= 65 and {c["key"] for c in good.components} == {"hrv", "rhr", "sleep", "load", "feel"}
    bad = load.readiness(rows + [{"date": TODAY.isoformat(), "rest_hr": 56, "sleep_score": 35, "feel": 2, "legs": 1}], TODAY, {"tsb": -28, "acwr": 1.6})
    assert bad.status in ("amber", "red") and bad.score < good.score
    sick = load.readiness(rows + [{"date": TODAY.isoformat(), "sick": True, "feel": 3}], TODAY)
    assert sick.status == "red"
    assert load.readiness([], TODAY).score is None  # no data, no made-up number


def test_slot_for_missed_key_session():
    missed = {"id": 1, "date": day(-1), "status": "planned", "data": {"sport": "running", "type": "intervals", "intensity": "high"}}
    up = [{"id": 2, "date": day(0), "status": "planned", "data": {"sport": "running", "type": "easy", "intensity": "low"}},
          {"id": 3, "date": day(1), "status": "planned", "data": {"sport": "running", "type": "threshold", "intensity": "moderate"}},
          {"id": 4, "date": day(3), "status": "planned", "data": {"sport": "running", "type": "easy", "intensity": "low"}}]
    sl = replan.slot_for(missed, up, TODAY)
    assert sl["date"] == day(3) and sl["replaces"]["id"] == 4  # today is next to tomorrow's threshold
    assert replan.vdot_factor(4) == 1.0 and 0.92 < replan.vdot_factor(28) < 0.94
    p = replan.break_protocol(6, "illness")
    assert p["easy_days"] == 6 and p["notes"]


def test_replan_apply_and_break(monkeypatch):
    monkeypatch.setattr(S, "push_to_garmin", lambda s, ids: [{"id": i, "ok": True} for i in ids])
    uid = new_user("replan")
    with as_user(uid), Session(engine) as s:
        S.update_athlete(s, vdot=45.0)
        miss = run("Series 6×800", day(-1), "intervals", "high")
        easy_lost = run("Rodaje", day(-3))
        tgt = run("Rodaje suave", day(2))
        for w in (miss, easy_lost, tgt, run("Tempo", day(0), "threshold", "moderate")):
            s.add(w)
        s.commit()
        chk = S.replan_check(s)
        m = {x["title"]: x for x in chk["missed"]}
        assert m["Series 6×800"]["slot"]["date"] == day(2) and not m["Rodaje"]["key"]
        r = S.replan_apply(s, miss.id, True)
        s.refresh(miss)
        s.refresh(tgt)
        assert miss.date == day(2) and tgt.status == "skipped" and "pasa al" in r["message"]
        assert [x["title"] for x in S.auto_skip_missed(s)] == []
        s.refresh(easy_lost)
        assert easy_lost.status == "skipped"
        # a run done a day late still completes the missed session
        late = run("Umbral", day(-2), "threshold", "moderate")
        s.add(late)
        s.commit()
        S.upsert_activity(s, {"external_id": "file:late", "date": day(-1), "sport": "running", "distance_m": 9000, "duration_s": 2700})
        s.refresh(late)
        assert late.status == "done"
        # 10 days ill: past sessions closed, paces eased, next days easy
        s.add(run("Series", day(-2), "intervals", "high"))
        q = run("Cuestas", day(1), "hills", "high")
        s.add(q)
        s.commit()
        b = S.report_break(s, 10, "illness")
        s.refresh(q)
        assert b["vdot"] < 45 and q.data["intensity"] == "low" and q.status == "modified" and "enfermedad" in q.note


def test_ai_daily_limit():
    uid = new_user("quota")
    admin = new_user("quota-admin", admin=True)
    with as_user(uid), Session(engine) as s:
        with Session(engine) as s2:
            u = s2.get(User, uid)
            u.ai_daily_limit = 2
            s2.add(u)
            s2.commit()
        assert S.ai_allowed(s) and S.ai_allowed(s, "readiness") and not S.ai_allowed(s)
        assert S.ai_usage(s)["count"] == 2 and "límite de 2" in S.ai_limit_message(s)
    with as_user(admin), Session(engine) as s:
        assert S.ai_usage(s)["limit"] is None and all(S.ai_allowed(s) for _ in range(5))


def test_readiness_view_proposal(monkeypatch):
    monkeypatch.setattr(S, "push_to_garmin", lambda s, ids: [{"id": i, "ok": True} for i in ids])
    from app.ai import coach
    monkeypatch.setattr(coach, "complete", lambda *a, **k: "Hoy mejor suave.")
    uid = new_user("ready")
    with as_user(uid), Session(engine) as s:
        S.update_athlete(s, vdot=45.0)
        w = run("Series 5×1000", TODAY.isoformat(), "intervals", "high")
        w.data["steps"] = [{"kind": "repeat", "repeat": 5, "steps": [{"kind": "run", "duration_type": "distance", "duration_value": 1000}]}]
        s.add(w)
        s.commit()
        v = S.save_checkin(s, 1, 1, sick=True)
        assert v["readiness"]["status"] == "red" and v["proposal"]["from"] == "Series 5×1000"
        assert S.readiness_view(s, explain=True)["explanation"] == "Hoy mejor suave."
        v = S.apply_readiness(s, True)
        s.refresh(w)
        assert w.status == "modified" and v["proposal"] is None


def test_deep_health_reports_stalled_scheduler(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main, scheduler
    c = TestClient(main.app)
    assert c.get("/api/health").json() == {"ok": True}
    monkeypatch.setitem(scheduler.STATE, "running", True)
    monkeypatch.setitem(scheduler.STATE, "interval_s", 60)
    monkeypatch.setitem(scheduler.STATE, "last_tick", dt.datetime.now().isoformat())
    assert c.get("/api/health?deep=1").status_code == 200
    monkeypatch.setitem(scheduler.STATE, "last_tick", (dt.datetime.now() - dt.timedelta(hours=1)).isoformat())
    r = c.get("/api/health?deep=1")
    assert r.status_code == 503 and "scheduler" in r.json()["problems"][0]
