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


def test_lan_pin_auth(monkeypatch):
    from app import auth
    c = TestClient(main.app)  # client host "testclient" = not this machine
    assert c.get("/api/athlete").status_code == 401
    monkeypatch.setattr(auth, "PASSWORD", "4321")
    monkeypatch.setattr(auth.time, "sleep", lambda _: None)
    assert c.post("/api/auth", json={"pin": "0000"}).status_code == 401
    r = c.post("/api/auth", json={"pin": "4321"})
    assert r.status_code == 200 and c.get("/api/athlete").status_code == 200
    assert c.get("/api/auth").json()["authed"] is True
    assert c.get("/api/health").status_code == 200 and r.headers["x-frame-options"] == "DENY"


def test_public_server_mode(monkeypatch):
    """Behind a reverse proxy nothing is trusted as local; password session or API token required."""
    from app import auth
    monkeypatch.setattr(auth, "PASSWORD", "correct horse battery")
    monkeypatch.setattr(auth, "TRUST_LOCAL", False)
    monkeypatch.setattr(auth, "TRUST_PROXY", True)
    monkeypatch.setattr(auth, "API_TOKEN", "t" * 40)
    monkeypatch.setattr(auth.time, "sleep", lambda _: None)
    monkeypatch.setattr(auth, "_fails", {})
    local = TestClient(main.app, client=("127.0.0.1", 5000))
    assert local.get("/api/athlete").status_code == 401  # proxy traffic looks local: must not be trusted
    assert local.get("/api/athlete", headers={"Authorization": "Bearer " + "t" * 40}).status_code == 200
    assert local.get("/api/athlete", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # rate limit is per real client (X-Forwarded-For), so an attacker can't lock the owner out
    for _ in range(10):
        local.post("/api/auth", json={"pin": "nope"}, headers={"X-Forwarded-For": "6.6.6.6"})
    assert local.post("/api/auth", json={"pin": "correct horse battery"}, headers={"X-Forwarded-For": "6.6.6.6"}).status_code == 429
    r = local.post("/api/auth", json={"pin": "correct horse battery"}, headers={"X-Forwarded-For": "1.2.3.4", "X-Forwarded-Proto": "https"})
    assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower()
    tok = r.cookies.get(auth.COOKIE) or local.cookies.get(auth.COOKIE)
    assert auth.valid_session(tok)
    monkeypatch.setattr(auth, "_KEY", b"x" * 32)  # password changed -> old sessions invalid
    assert not auth.valid_session(tok)
    monkeypatch.setattr(auth, "PASSWORD", "short")
    import pytest
    with pytest.raises(RuntimeError):
        auth.check_config()


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
