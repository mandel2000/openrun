import datetime as dt
import os
import tempfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "auto.db"))
os.environ["OPENRUN_SCHEDULER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app import main, scheduler  # noqa: E402
from app import services as S  # noqa: E402
from app.db import Activity, PlannedWorkout, engine, init_db  # noqa: E402
from app.training import analysis as AN  # noqa: E402
from app.training import heat as HEAT  # noqa: E402

PLAN = {"title": "Umbral 3×2 km", "sport": "running", "type": "threshold", "intensity": "moderate", "steps": [
    {"kind": "warmup", "duration_type": "distance", "duration_value": 2000, "zone": "easy", "pace_slow": 360, "pace_fast": 330},
    {"kind": "repeat", "repeat": 3, "steps": [
        {"kind": "run", "duration_type": "distance", "duration_value": 2000, "zone": "threshold", "pace_slow": 280, "pace_fast": 274},
        {"kind": "recovery", "duration_type": "time", "duration_value": 90}]},
    {"kind": "cooldown", "duration_type": "distance", "duration_value": 1500, "zone": "easy", "pace_slow": 360, "pace_fast": 330}]}


def laps(rep_pace: float, rep_hr: int):
    """Garmin-like lapDTOs: warmup(step 0), 3×[run(step 2), rest(step 3)], cooldown(step 4)."""
    out = [{"lapIndex": 1, "intensityType": "WARMUP", "wktStepIndex": 0, "distance": 2000, "movingDuration": 690, "averageHR": 130}]
    for r in range(3):
        out.append({"lapIndex": 2 + 2 * r, "intensityType": "ACTIVE", "wktStepIndex": 2, "distance": 2000, "movingDuration": rep_pace * 2, "averageHR": rep_hr})
        out.append({"lapIndex": 3 + 2 * r, "intensityType": "REST", "wktStepIndex": 3, "distance": 150, "movingDuration": 90, "averageHR": 140})
    out.append({"lapIndex": 8, "intensityType": "COOLDOWN", "wktStepIndex": 4, "distance": 1500, "movingDuration": 520, "averageHR": 135})
    return out


def test_step_index_matches_garmin_upload_order():
    m = AN.step_index_map(PLAN["steps"])
    assert m[0]["kind"] == "warmup" and m[2]["zone"] == "threshold" and m[3]["kind"] == "recovery" and m[4]["kind"] == "cooldown"
    assert 1 not in m  # the repeat group itself


def test_verdicts():
    on = AN.analyze(AN.normalize_laps(laps(277, 168)), PLAN, lthr=172)
    assert on["verdict"] == "on_target" and on["n_work"] == 3 and on["on_target_pct"] == 100
    easy = AN.analyze(AN.normalize_laps(laps(265, 166)), PLAN, lthr=172)
    assert easy["verdict"] == "too_easy" and easy["avg_dev_pct"] > 2
    fast_but_redlined = AN.analyze(AN.normalize_laps(laps(265, 178)), PLAN, lthr=172)
    assert fast_but_redlined["verdict"] != "too_easy"
    hard = AN.analyze(AN.normalize_laps(laps(292, 175)), PLAN, lthr=172)
    assert hard["verdict"] == "too_hard"
    assert AN.analyze(AN.normalize_laps(laps(277, 168)), None)["verdict"] is None  # no plan, no verdict


def test_pace_insight_rules():
    today = dt.date(2027, 3, 1)
    two_easy = [{"date": "2027-02-20", "verdict": "too_easy"}, {"date": "2027-02-24", "verdict": "too_easy"}]
    assert AN.pace_insight(two_easy, today, None, None, 45.0)["to"] == 45.5
    assert AN.pace_insight(two_easy, today, "2027-02-27", None, 45.0) is None  # changed < 7 days ago
    assert AN.pace_insight(two_easy, today, None, "2027-03-08", 45.0) is None  # goal race within 10 days
    assert AN.pace_insight(two_easy[:1], today, None, None, 45.0) is None
    two_hard = [{"date": "2027-02-25", "verdict": "too_hard"}, {"date": "2027-02-27", "verdict": "too_hard"}, {"date": "2027-02-28", "verdict": "too_easy"}]
    assert AN.pace_insight(two_hard, today, None, None, 45.0)["to"] == 44.5
    old = [{"date": "2026-12-01", "verdict": "too_easy"}, {"date": "2026-12-05", "verdict": "too_easy"}]
    assert AN.pace_insight(old, today, None, None, 45.0) is None


def test_heat_table_and_scaling():
    assert HEAT.slowdown_pct(10, 2)[0] == 0  # 50+35.6 °F
    pct, s = HEAT.slowdown_pct(28, 18)  # 82.4+64.4 = 146.8 °F
    assert pct == 5.3 and s == 147
    assert HEAT.slowdown_pct(38, 26)[0] == 11.0  # 179 °F
    assert HEAT.slowdown_pct(38, 29)[0] == 12.0  # > 180 °F
    st = HEAT.scale_steps(PLAN["steps"], 5)
    assert st[1]["steps"][0]["pace_fast"] == round(274 * 1.05, 1) and PLAN["steps"][1]["steps"][0]["pace_fast"] == 274


def test_apply_heat_and_restore(monkeypatch):
    init_db()
    today = dt.date.today().isoformat()
    with Session(engine) as s:
        S.update_settings(s, lat=40.96, lon=-5.66, run_hour=8)
        pw = PlannedWorkout(date=today, data={**PLAN, "date": today}, week=0)
        s.add(pw)
        s.commit()
        s.refresh(pw)
        hot = {f"{today}T08:00": {"temp": 28, "dew": 18, "rh": 55}}
        monkeypatch.setattr(HEAT, "forecast", lambda lat, lon: hot)
        ch = S.apply_heat(s, days=1)
        assert any(c["id"] == pw.id and c["pct"] == 5.3 for c in ch)
        s.refresh(pw)
        assert pw.data["steps"][1]["steps"][0]["pace_fast"] == round(274 * 1.053, 1) and "calor" in pw.note
        assert S.apply_heat(s, days=1) == [] or all(c["id"] != pw.id for c in S.apply_heat(s, days=1))  # idempotent
        hot[f"{today}T08:00"] = {"temp": 12, "dew": 4, "rh": 60}
        S.apply_heat(s, days=1)
        s.refresh(pw)
        assert pw.data["steps"][1]["steps"][0]["pace_fast"] == 274 and "_heat" not in pw.data
        s.delete(pw)
        s.commit()


def test_push_changed_only_pushes_new_or_modified(monkeypatch):
    init_db()
    pushed = []

    def fake_push(s, ids):
        pushed.append(list(ids))
        for i in ids:
            w = s.get(PlannedWorkout, i)
            w.garmin_workout_id = f"g{i}"
            s.add(w)
        s.commit()
        return [{"id": i, "ok": True} for i in ids]

    monkeypatch.setattr(S, "push_to_garmin", fake_push)
    day = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    with Session(engine) as s:
        pw = PlannedWorkout(date=day, data={**PLAN, "date": day}, week=0)
        s.add(pw)
        s.commit()
        S.push_changed(s)
        assert pw.id in pushed[-1]
        n = len(pushed)
        S.push_changed(s)
        assert len(pushed) == n or pw.id not in pushed[-1]  # unchanged -> not re-pushed
        pw.data = {**pw.data, "title": "Umbral 4×2 km"}
        s.add(pw)
        s.commit()
        S.push_changed(s)
        assert pw.id in pushed[-1]
        s.delete(pw)
        s.commit()


def test_analyze_activity_links_plan(monkeypatch):
    init_db()
    with Session(engine) as s:
        pw = PlannedWorkout(date="2027-01-12", data={**PLAN, "date": "2027-01-12"}, week=0)
        s.add(pw)
        s.commit()
        act = S.upsert_activity(s, {"external_id": "garmin:999", "date": "2027-01-12", "sport": "running", "distance_m": 10000, "duration_s": 2900})
        s.refresh(pw)
        assert pw.activity_id == act.id
        res = S.analyze_activity(s, act, laps_raw=laps(265, 166))
        assert res["verdict"] == "too_easy" and res["planned_id"] == pw.id
        assert s.get(Activity, act.id).data["analysis"]["n_work"] == 3


def test_scheduler_due():
    st = {"auto_sync": True, "sync_time": "06:30"}
    assert scheduler.due(st, None, dt.datetime(2027, 1, 1, 7, 0))
    assert not scheduler.due(st, "2027-01-01", dt.datetime(2027, 1, 1, 7, 0))
    assert not scheduler.due(st, None, dt.datetime(2027, 1, 1, 6, 0))
    assert not scheduler.due({**st, "auto_sync": False}, None, dt.datetime(2027, 1, 1, 7, 0))


def _fresh_users(monkeypatch, password):
    from sqlalchemy import delete

    from app import auth
    from app.db import Invite, User
    with Session(engine) as s:
        s.exec(delete(User))
        s.exec(delete(Invite))
        s.commit()
    monkeypatch.setattr(auth, "PASSWORD", password)
    monkeypatch.setattr(auth.time, "sleep", lambda _: None)
    monkeypatch.setattr(auth, "_fails", {})
    auth.ensure_admin()
    return auth


def test_lan_pin_auth(monkeypatch):
    auth = _fresh_users(monkeypatch, "4321")
    c = TestClient(main.app)  # client host "testclient" = not this machine
    assert c.get("/api/athlete").status_code == 401
    assert c.post("/api/auth", json={"pin": "0000"}).status_code == 401
    r = c.post("/api/auth", json={"pin": "4321"})  # old PIN-only screen logs in as the admin
    assert r.status_code == 200 and c.get("/api/athlete").status_code == 200
    me = c.get("/api/auth").json()
    assert me["authed"] is True and me["user"]["is_admin"] and me["user"]["username"] == auth.ADMIN_USERNAME
    assert c.get("/api/health").status_code == 200 and r.headers["x-frame-options"] == "DENY"


def test_public_server_mode(monkeypatch):
    """Behind a reverse proxy nothing is trusted as local; password session or API token required."""
    auth = _fresh_users(monkeypatch, "correct horse battery")
    monkeypatch.setattr(auth, "TRUST_LOCAL", False)
    monkeypatch.setattr(auth, "TRUST_PROXY", True)
    monkeypatch.setattr(auth, "API_TOKEN", "t" * 40)
    local = TestClient(main.app, client=("127.0.0.1", 5000))
    assert local.get("/api/athlete").status_code == 401  # proxy traffic looks local: must not be trusted
    assert local.get("/api/athlete", headers={"Authorization": "Bearer " + "t" * 40}).status_code == 200
    assert local.get("/api/athlete", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # rate limit is per real client (X-Forwarded-For), so an attacker can't lock the owner out
    for _ in range(10):
        local.post("/api/auth", json={"username": "admin", "password": "nope"}, headers={"X-Forwarded-For": "6.6.6.6"})
    assert local.post("/api/auth", json={"username": "admin", "password": "correct horse battery"},
                      headers={"X-Forwarded-For": "6.6.6.6"}).status_code == 429
    r = local.post("/api/auth", json={"username": "admin", "password": "correct horse battery"},
                   headers={"X-Forwarded-For": "1.2.3.4", "X-Forwarded-Proto": "https"})
    assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower()
    tok = r.cookies.get(auth.COOKIE) or local.cookies.get(auth.COOKIE)
    assert auth.session_user(tok) == 1
    # changing the password invalidates old sessions
    r = local.put("/api/account", json={"current_password": "correct horse battery", "new_password": "otra contraseña larga"},
                  headers={"X-Forwarded-For": "1.2.3.4", "Cookie": f"{auth.COOKIE}={tok}"})
    assert r.status_code == 200 and auth.session_user(tok) is None
    monkeypatch.setattr(auth, "PASSWORD", "short")
    import pytest
    with pytest.raises(RuntimeError):
        auth.check_config()


def test_multi_user_isolation(monkeypatch):
    auth = _fresh_users(monkeypatch, "admin password 1")
    admin = TestClient(main.app)
    assert admin.post("/api/auth", json={"username": "admin", "password": "admin password 1"}).status_code == 200
    admin.put("/api/athlete", json={"name": "Alex", "vdot": 47})
    with Session(engine) as s:
        S.add_race(s, "Behobia", "2027-11-08", 20000, "A")
    # invitations: only admins, single use, brute force throttled
    inv = admin.post("/api/users/invites", json={"note": "amigo"}).json()
    friend = TestClient(main.app)
    assert friend.post("/api/auth/register", json={"code": "nope", "username": "x1x", "password": "y" * 12}).status_code == 403
    assert friend.post("/api/auth/register", json={"code": inv["code"], "username": "ana", "password": "corta"}).status_code == 400
    r = friend.post("/api/auth/register", json={"code": inv["code"], "username": "Ana", "name": "Ana", "password": "ana password 1"})
    assert r.status_code == 200 and r.json()["user"]["username"] == "ana"
    assert TestClient(main.app).post("/api/auth/register", json={"code": inv["code"], "username": "eve", "password": "e" * 12}).status_code == 403
    # each user sees only their own data
    assert friend.get("/api/athlete").json()["name"] == "Atleta"
    assert friend.get("/api/races").json() == []
    friend.put("/api/athlete", json={"name": "Ana", "vdot": 40})
    assert admin.get("/api/athlete").json()["name"] == "Alex"
    assert [r["name"] for r in admin.get("/api/races").json()] == ["Behobia"]
    assert friend.get("/api/users").status_code == 403
    users = admin.get("/api/users").json()
    assert [u["username"] for u in users["users"]] == ["admin", "ana"] and users["invites"] == []
    # without a user in context, tenant tables are off limits
    from app import tenancy
    tok = tenancy.set_user(None)
    try:
        import pytest
        with pytest.raises(tenancy.NoUserContext), Session(engine) as s:
            S.list_races(s)
    finally:
        tenancy.reset_user(tok)
    uid = users["users"][1]["id"]
    assert admin.delete(f"/api/users/{uid}").status_code == 200
    assert friend.get("/api/athlete").status_code == 401


def test_single_user_db_migrates_to_admin(tmp_path):
    import sqlite3

    from sqlalchemy import create_engine
    from sqlmodel import select

    from app import db
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE athlete (id INTEGER PRIMARY KEY, name VARCHAR, sex VARCHAR, age INTEGER, max_hr INTEGER, rest_hr INTEGER,
                              lthr INTEGER, vdot FLOAT, vdot_source VARCHAR, weekly_km FLOAT);
        INSERT INTO athlete (id, name, sex, vdot) VALUES (1, 'Alex', 'male', 47.5);
        CREATE TABLE meta (key VARCHAR PRIMARY KEY, value JSON);
        INSERT INTO meta VALUES ('settings', '{"sync_time": "07:00"}');
        CREATE TABLE activity (id INTEGER PRIMARY KEY, external_id VARCHAR, date VARCHAR, sport VARCHAR, data JSON, trimp FLOAT);
        CREATE UNIQUE INDEX ix_activity_external_id ON activity (external_id);
        INSERT INTO activity VALUES (1, 'garmin:1', '2026-10-01', 'running', '{}', 50);
    """)
    con.close()
    old_engine, old_path = db.engine, db.DB_PATH
    db.engine, db.DB_PATH = create_engine(f"sqlite:///{path}"), path
    try:
        db.init_db()
        assert (tmp_path / "old-pre-multiuser.db").exists()
        from app.tenancy import as_user
        with as_user(1), Session(db.engine) as s:
            assert S.get_athlete(s).vdot == 47.5
            assert S.get_settings(s)["sync_time"] == "07:00"
            assert len(s.exec(select(Activity)).all()) == 1
        with as_user(2), Session(db.engine) as s:
            assert S.get_athlete(s).name == "Atleta" and S.get_settings(s)["sync_time"] == "06:30"
            s.add(Activity(external_id="garmin:1", date="2026-10-01"))  # same id, other user: allowed now
            s.commit()
    finally:
        db.engine, db.DB_PATH = old_engine, old_path


def test_tools_endpoint_and_remote_mcp(monkeypatch):
    from app import auth, mcp_server
    monkeypatch.setattr(auth, "API_TOKEN", "k" * 40)
    c = TestClient(main.app)
    h = {"Authorization": "Bearer " + "k" * 40}
    assert c.post("/api/tools/calculate_vdot", json={"args": {"distance": "5k", "time": "20:00"}}).status_code == 401
    r = c.post("/api/tools/calculate_vdot", json={"args": {"distance": "5k", "time": "20:00"}}, headers=h).json()
    assert r["ok"] and 49 < r["result"]["vdot"] < 50.5
    assert c.post("/api/tools/rm_rf", json={"args": {}}, headers=h).status_code == 404
    # the MCP server forwards to the HTTP API when OPENRUN_URL is set
    import httpx
    monkeypatch.setattr(mcp_server, "REMOTE_URL", "https://run.example")
    monkeypatch.setattr(mcp_server, "REMOTE_TOKEN", "k" * 40)
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout, headers: c.post(url.replace("https://run.example", ""), json=json, headers=headers))
    res = mcp_server.call("calculate_vdot", {"distance": "5k", "time": "20:00"})
    assert not res.is_error and '"vdot"' in res.content[0].text


def test_move_workout_swaps_and_warns(monkeypatch):
    from app.db import Plan
    monkeypatch.setattr(S, "push_to_garmin", lambda s, ids: [{"id": i, "ok": True} for i in ids])
    d = [(dt.date.today() + dt.timedelta(days=i)).isoformat() for i in range(1, 5)]
    with Session(engine) as s:
        p = Plan(name="t", goal="10k")
        s.add(p)
        s.commit()
        mk = lambda date, title, typ, inten, gid=None: PlannedWorkout(plan_id=p.id, date=date, data={  # noqa: E731
            "title": title, "type": typ, "intensity": inten, "sport": "running", "steps": []}, garmin_workout_id=gid)
        a, b = mk(d[0], "Series", "intervals", "high", "g1"), mk(d[2], "Largo", "long", "low")
        s.add(a)
        s.add(b)
        s.commit()
        r = S.move_workout(s, a.id, d[2], swap=True)
        assert {x["title"]: x["date"] for x in r["moved"]} == {"Series": d[2], "Largo": d[0]}
        assert r["watch"] == {"ok": 1, "failed": 0} and r["warnings"] == []
        r = S.move_workout(s, a.id, d[1], swap=True)  # series the day after the long run
        assert r["warnings"] and "seguidos" in r["warnings"][0]
        import pytest
        with pytest.raises(ValueError):
            S.move_workout(s, a.id, "2020-01-01")


def test_weekly_review_facts_and_cache(monkeypatch):
    from app.ai import coach
    calls = []
    monkeypatch.setattr(coach, "complete", lambda system, prompt, **kw: calls.append(prompt) or "Buena semana.")
    monday = dt.date(2027, 3, 1)
    with Session(engine) as s:
        s.add(Activity(external_id="garmin:wr1", date="2027-03-02", sport="running", trimp=60,
                       data={"distance_m": 10000, "duration_s": 3000, "avg_hr": 150, "name": "Rodaje"}))
        s.add(PlannedWorkout(date="2027-03-02", status="done", data={"title": "Rodaje", "sport": "running", "distance_km": 10, "duration_min": 50, "low_intensity_min": 50}))
        s.add(PlannedWorkout(date="2027-03-04", status="skipped", data={"title": "Series", "sport": "running", "distance_km": 9, "intensity": "high"}))
        s.commit()
        r = S.weekly_review(s, monday.isoformat())
        f = r["facts"]
        assert f["km"] == 10.0 and f["km_plan"] == 10 and f["hechas"] == 1 and f["saltadas"] == 1 and f["cumplimiento_pct"] == 50
        assert f["salidas"][0]["ritmo"] == "5:00" and r["comment"] == "Buena semana." and r["ai"]
        S.weekly_review(s, "2027-03-03")  # any day of the week -> same cached review
        assert len(calls) == 1
        monkeypatch.setattr(coach, "complete", lambda *a, **k: None)
        r = S.weekly_review(s, monday.isoformat(), regenerate=True)
        assert not r["ai"] and "1 de 2" in r["comment"]


def test_push_subscribe_send_and_cleanup(monkeypatch, tmp_path):
    import pywebpush

    from app import push
    monkeypatch.setattr(push, "KEY_FILE", tmp_path / "vapid.pem")
    assert len(push.public_key()) > 80 and (tmp_path / "vapid.pem").exists()
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BNc" + "A" * 84, "auth": "x" * 22}}
    push.subscribe(1, sub)
    push.subscribe(1, sub)  # idempotent
    assert push.count(1) == 1
    sent = []
    monkeypatch.setattr(pywebpush, "webpush", lambda info, data, **kw: sent.append((info["endpoint"], data)))
    assert push.send(1, "Hoy: Series", "6×800 m") == 1 and "Series" in sent[0][1]

    class Gone(pywebpush.WebPushException):
        def __init__(self):
            super().__init__("gone", response=type("R", (), {"status_code": 410})())

    def boom(*a, **k):
        raise Gone()
    monkeypatch.setattr(pywebpush, "webpush", boom)
    assert push.send(1, "x", "y") == 0 and push.count(1) == 0  # expired subscription removed


def test_today_message(monkeypatch):
    today = dt.date.today().isoformat()
    with Session(engine) as s:
        for pw in s.exec(__import__("sqlmodel").select(PlannedWorkout).where(PlannedWorkout.date == today)).all():
            s.delete(pw)
        s.add(PlannedWorkout(date=today, data={"title": "Series 6×800", "sport": "running", "distance_km": 9, "_heat": {"pct": 2.5}}))
        s.add(PlannedWorkout(date=today, data={"title": "Fuerza general", "sport": "strength"}))
        s.commit()
        title, body = S.today_message(s)
        assert title == "Hoy: Series 6×800" and "9 km" in body and "calor" in body and "Fuerza general" in body
