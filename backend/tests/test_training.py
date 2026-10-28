import datetime as dt
import os
import tempfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

import pytest  # noqa: E402

from app.integrations.garmin import workout_to_garmin  # noqa: E402
from app.integrations.zepp import parse_csv  # noqa: E402
from app.training import adapt, load  # noqa: E402
from app.training.plan import PlanRequest, generate_plan  # noqa: E402
from app.training.vdot import parse_time, predict_race_time, training_paces, vdot_from_race  # noqa: E402


def test_vdot_matches_daniels_tables():
    # Daniels' table: 5K 19:57 ~ VDOT 50; marathon 3:10:49 ~ VDOT 50
    assert vdot_from_race(5000, parse_time("19:57")) == pytest.approx(50, abs=0.3)
    assert vdot_from_race(42195, parse_time("3:10:49")) == pytest.approx(50, abs=0.3)
    assert predict_race_time(50, 10000) == pytest.approx(parse_time("41:21"), abs=15)


def test_pace_order():
    p = training_paces(50)
    order = [p.easy.mid(), p.marathon.mid(), p.threshold.mid(), p.interval.mid(), p.repetition.mid()]
    assert order == sorted(order, reverse=True)
    assert p.threshold.mid() == pytest.approx(4 * 60 + 15, abs=8)  # Daniels T ~4:15/km @ VDOT 50


@pytest.mark.parametrize("goal,days,level,km", [("5k", 3, "beginner", 10), ("10k", 5, "intermediate", 35),
                                                ("half", 4, "intermediate", 30), ("marathon", 5, "intermediate", 40),
                                                ("marathon", 7, "advanced", 80), ("base", 4, "beginner", 12)])
def test_plan_principles(goal, days, level, km):
    plan = generate_plan(PlanRequest(goal=goal, start_date=dt.date(2026, 11, 2), days_per_week=days, level=level,
                                     current_weekly_km=km, longest_recent_run_km=km / 3,
                                     recent_race_distance="5k", recent_race_time_s=1500))
    weeks = plan["weeks"]
    prev = None
    for w in weeks:
        runs = [x for x in w["workouts"] if x["sport"] == "running"]
        hard = [x for x in runs if x["intensity"] == "high"]
        assert len(hard) <= 2, f"week {w['index']} has {len(hard)} high-intensity sessions"
        assert len({x["date"] for x in runs}) <= days
        if w["phase"] not in ("taper",) and not w["is_recovery"] and prev:
            assert w["target_km"] <= prev * 1.11, "weekly volume jump > 10%"
        if w["phase"] != "taper":
            assert w["low_intensity_pct"] >= 70
        prev = w["target_km"] if not w["is_recovery"] else prev
    if goal != "base":
        assert weeks[-1]["workouts"][-1]["type"] == "race"
        assert weeks[-1]["phase"] == "taper"


def test_race_date_alignment():
    plan = generate_plan(PlanRequest(goal="half", start_date=dt.date(2026, 11, 2), race_date=dt.date(2027, 2, 14),
                                     days_per_week=4, current_weekly_km=30))
    assert plan["weeks"][-1]["workouts"][-1]["date"] == "2027-02-14"


def test_garmin_json_shape():
    plan = generate_plan(PlanRequest(goal="10k", start_date=dt.date(2026, 11, 2), days_per_week=5, current_weekly_km=40))
    w = next(x for wk in plan["weeks"] for x in wk["workouts"] if x["type"] == "intervals")
    g = workout_to_garmin(w)
    steps = g["workoutSegments"][0]["workoutSteps"]
    rep = next(s for s in steps if s["type"] == "RepeatGroupDTO")
    work = rep["workoutSteps"][0]
    assert work["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert work["targetValueOne"] < work["targetValueTwo"]  # slower pace = lower m/s first
    orders = []

    def collect(ss):
        for s in ss:
            orders.append(s["stepOrder"])
            collect(s.get("workoutSteps", []))
    collect(steps)
    assert len(orders) == len(set(orders))


def test_readiness_hrv():
    base = [{"date": (dt.date(2026, 10, 1) + dt.timedelta(days=i)).isoformat(), "hrv_rmssd": 60 + (i % 5)} for i in range(20)]
    low = [{"date": (dt.date(2026, 10, 21) + dt.timedelta(days=i)).isoformat(), "hrv_rmssd": 40} for i in range(5)]
    r = load.readiness(base + low, today=dt.date(2026, 10, 25))
    assert r.status in ("amber", "red")
    r2 = load.readiness(base, today=dt.date(2026, 10, 20))
    assert r2.status == "green"


def test_adapt_amber_reduces_reps():
    plan = generate_plan(PlanRequest(goal="10k", start_date=dt.date(2026, 11, 2), days_per_week=5, current_weekly_km=40))
    w = next(x for wk in plan["weeks"] for x in wk["workouts"] if x["type"] == "intervals")
    new, _ = adapt.adjust_for_readiness(w, "amber", 45)
    assert new["distance_km"] < w["distance_km"]
    red, _ = adapt.adjust_for_readiness(w, "red", 45)
    assert red["intensity"] == "low"


def test_rmssd_and_trimp():
    rr = [800 + (20 if i % 2 else -20) for i in range(120)]
    assert load.rmssd(rr) == pytest.approx(40, abs=1)
    assert load.trimp(60, 150, 50, 190) > load.trimp(60, 130, 50, 190)


def test_zepp_csv():
    csv = "date,time,heartRate\n" + "\n".join(f"2026-10-20,0{i % 10}:00,{50 + i % 30}" for i in range(100))
    rows = parse_csv(csv)
    assert rows and rows[0]["rest_hr"] <= 52
    csv2 = "Date,HRV (ms),Resting heart rate,Sleep score\n2026-10-20,55,48,80\n2026-10-21,60,47,85\n"
    rows2 = parse_csv(csv2)
    assert rows2[1] == {"date": "2026-10-21", "source": "zepp", "hrv_rmssd": 60.0, "rest_hr": 47, "sleep_score": 85}

