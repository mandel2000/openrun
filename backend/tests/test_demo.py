import os
import tempfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "demo.db"))
os.environ["OPENRUN_SCHEDULER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app import demo, main  # noqa: E402
from app import services as S  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.tenancy import as_user  # noqa: E402


def test_demo_login_data_and_limits(monkeypatch):
    init_db()
    c = TestClient(main.app, client=("203.0.113.9", 5000))
    monkeypatch.delenv("OPENRUN_DEMO", raising=False)
    assert c.post("/api/auth/demo").status_code == 404
    monkeypatch.setenv("OPENRUN_DEMO", "1")
    assert c.get("/api/auth").json()["demo"] is True
    me = c.post("/api/auth/demo").json()["user"]
    assert me["is_demo"] and me["username"] == "demo"

    # a plan, history and wellness to look at
    plan = c.get("/api/plan").json()
    assert plan and any(w["status"] == "done" for wk in plan["weeks"] for w in wk["workouts"])
    acts = c.get("/api/activities?days=120").json()
    runs = [a for a in acts if a["sport"] == "running"]
    analysed = [a for a in runs if (a.get("analysis") or {}).get("verdict")]
    assert len(runs) > 20 and analysed
    assert c.get(f"/api/activities/{analysed[0]['id']}/analysis").json()["laps"]
    assert c.get(f"/api/activities/{runs[0]['id']}/detail").json()["has_streams"]
    assert c.get("/api/records").json()["records"]["all"].get("5k")
    assert c.get("/api/races").json()
    assert c.get("/api/readiness").json()["readiness"]["score"] is not None
    assert all(r.get("rest_hr") and r.get("hrv_rmssd") for r in c.get("/api/wellness?days=30").json()["rows"])

    # what the demo can't do
    assert c.post("/api/garmin/login", json={"email": "x@example.com", "password": "x"}).status_code == 403
    assert c.post("/api/chat/stream", json={"message": "hola"}).status_code == 403
    assert c.post("/api/account/token").status_code == 403
    assert c.put("/api/account", json={"new_password": "something-long-enough"}).status_code == 403
    assert c.put("/api/account", json={"lang": "es"}).status_code == 200
    with as_user(me["id"]), Session(engine) as s:
        assert S.ai_allowed(s) is False
    # but it can play with the plan
    assert c.post("/api/readiness/checkin", json={"feel": 4, "legs": 3}).status_code == 200


def test_demo_resets(monkeypatch):
    monkeypatch.setenv("OPENRUN_DEMO", "1")
    u = demo.demo_user()
    with as_user(u.id), Session(engine) as s:
        S.create_plan(s, {"goal": "5k", "weeks": 6})
    demo.reset(u.id)
    with as_user(u.id), Session(engine) as s:
        assert S.plan_overview(s)["goal"] == "half"
