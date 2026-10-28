import os
import tempfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "rp.db"))

from sqlmodel import Session  # noqa: E402

from app import services as S  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.training import race_plan as RP  # noqa: E402

GPX = b"""<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>""" + b"".join(
    f'<trkpt lat="{43.30 + i * 0.0009:.5f}" lon="-1.98"><ele>{10 + (40 if 20 <= i < 30 else 0) * (i - 20) / 10 if i < 30 else 50 - (i - 30) * 4 if i < 40 else 10}</ele></trkpt>'.encode()
    for i in range(0, 56)) + b"</trkseg></trk></gpx>"


def test_effort_factor_shape():
    assert RP.effort_factor(0) == 1
    assert RP.effort_factor(0.04) > 1.1 > RP.effort_factor(0.01) > 1
    assert 0.85 < RP.effort_factor(-0.04) < 1  # downhill helps, but less than uphill hurts
    assert RP.effort_factor(0.5) == RP.effort_factor(0.15)


def test_pace_plan_hits_target_and_slows_on_climbs():
    prof = RP.BUILTIN["behobia"]["profile"]
    plan = RP.pace_plan(prof, 5700, RP.BUILTIN["behobia"]["notes"])
    assert abs(plan["total_s"] - 5700) <= 1 and len(plan["kms"]) == 20
    k = {x["km"]: x for x in plan["kms"]}
    assert k[17]["pace_s"] > k[16]["pace_s"] > k[18]["pace_s"]  # Miracruz slower, the descent faster
    assert k[1]["pace_s"] > k[4]["pace_s"]  # conservative start
    assert k[7]["note"] and "Gaintxurizketa" in k[7]["note"]
    gain, _ = RP.gain_loss(prof)
    assert 170 <= gain <= 210  # organiser: 192 m D+


def test_gpx_profile_and_watch_steps():
    pts = RP.parse_track("x.gpx", GPX)
    prof = RP.profile_from_track(pts)
    assert 5500 < prof[-1][0] < 6500 and len(prof) > 50
    plan = RP.pace_plan(prof, 1800)
    steps = RP.watch_steps(plan["kms"])
    assert len(steps) == len(plan["kms"]) and steps[0]["pace_slow"] > steps[0]["pace_fast"]


def test_race_strategy_service(monkeypatch):
    init_db()
    monkeypatch.setattr(S, "race_weather", lambda *a: {"temp": 22, "dew": 14, "slowdown_pct": 2.5, "hour": 10})
    with Session(engine) as s:
        S.update_athlete(s, vdot=46.0)
        r = S.add_race(s, "Behobia-San Sebastián", "2027-11-14", 20000, "A")
        rid = r["id"]
        st = S.race_strategy(s, rid)
        assert st["course"]["builtin"] and st["course"]["approx"]
        assert st["prediction"]["course_s"] > st["prediction"]["flat_s"]  # hilly course costs time
        assert abs(st["target_s"] - st["prediction"]["course_s"] * 1.025) < 2  # heat
        st = S.save_race_strategy(s, rid, None, 5600, "11:00")
        assert st["mode"] == "custom" and abs(st["target_s"] - 5600 * 1.025) < 2 and st["start_time"] == "11:00"
        st = S.set_race_course(s, rid, "x.gpx", GPX)
        assert not st["course"]["builtin"] and st["course"]["coords"]
        monkeypatch.setattr(S.garmin, "status", lambda: {"connected": False})
        out = S.push_race_strategy(s, rid)
        assert out["workout"]["type"] == "race" and len(out["workout"]["steps"]) == len(st["kms"])
        again = S.push_race_strategy(s, rid)  # replaces, doesn't duplicate
        assert again["workout"]["id"] == out["workout"]["id"]


def test_km_splits_and_streams():
    from app.integrations.garmin import streams_from_details
    n = 400
    det = {"metricDescriptors": [{"key": "sumDuration", "metricsIndex": 0}, {"key": "sumDistance", "metricsIndex": 1},
                                 {"key": "directHeartRate", "metricsIndex": 2}, {"key": "directElevation", "metricsIndex": 3},
                                 {"key": "directLatitude", "metricsIndex": 4}, {"key": "directLongitude", "metricsIndex": 5}],
           "activityDetailMetrics": [{"metrics": [i * 6.0, i * 25.0, 140 + i % 10, 800 + (i % 40), 40.8 + i * 1e-5, -5.5]} for i in range(n)]}
    st = streams_from_details(det, max_points=200)
    assert len(st["t"]) == 200 and st["d"][-1] == 9975.0
    sp = S.km_splits(st)
    assert len(sp) == 10 and all(230 < x["pace_s"] < 250 for x in sp[:-1])  # 6 s per 25 m = 4:00/km
    assert sp[0]["hr"] and sp[0]["gain_m"] > 0
