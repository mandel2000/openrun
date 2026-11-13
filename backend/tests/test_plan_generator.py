"""Plan generator v2: any running days, chosen weekdays, weekly ceiling, session-spike limit,
variety of formats and optional strength on chosen days."""

import datetime as dt
import os
import tempfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

import pytest  # noqa: E402

from app.training.plan import PlanRequest, day_roles, generate_plan  # noqa: E402

START = dt.date(2026, 11, 2)  # a Monday


def _runs(week):
    return [x for x in week["workouts"] if x["sport"] == "running"]


def _weekday(x):
    return dt.date.fromisoformat(x["date"]).weekday()


@pytest.mark.parametrize("days", [1, 2, 3, 4, 5, 6, 7])
@pytest.mark.parametrize("goal", ["5k", "10k", "half", "marathon", "base"])
def test_any_number_of_days(goal, days):
    plan = generate_plan(PlanRequest(goal=goal, start_date=START, days_per_week=days, current_weekly_km=6 * days,
                                     longest_recent_run_km=8, level="intermediate"))
    longest = 8.0
    for w in plan["weeks"]:
        runs = _runs(w)
        assert len({x["date"] for x in runs}) <= days
        assert sum(1 for x in runs if x["intensity"] == "high") <= 2
        if w["phase"] != "taper":
            assert w["low_intensity_pct"] >= 70, (w["index"], w["low_intensity_pct"])
        for x in runs:
            if x["type"] != "race":
                # single-session spike: never > ~10% over the longest run so far (Frandsen 2025)
                assert x["distance_km"] <= longest * 1.1 + 0.6, (w["index"], x["title"], x["distance_km"], longest)
        longest = max([longest] + [x["distance_km"] for x in runs if x["type"] != "race"])
    if goal != "base":
        assert plan["weeks"][-1]["workouts"][-1]["type"] == "race"


def test_chosen_run_days_are_respected():
    days = [0, 2, 5]  # Mon, Wed, Sat
    plan = generate_plan(PlanRequest(goal="half", start_date=START, run_days=days, long_run_day=5, current_weekly_km=25))
    assert plan["days_per_week"] == 3 and plan["run_days"] == days
    for w in plan["weeks"][:-1]:  # race week is special (race date + shakeout)
        assert {_weekday(x) for x in _runs(w)} <= set(days)
        long = [x for x in _runs(w) if x["type"] == "long"]
        assert all(_weekday(x) == 5 for x in long)


def test_long_day_falls_back_to_a_run_day():
    plan = generate_plan(PlanRequest(goal="10k", start_date=START, run_days=[1, 3], long_run_day=6, weeks=8))
    assert plan["long_run_day"] == 3


def test_quality_days_spread_away_from_long_run():
    roles = day_roles([0, 1, 2, 3, 4, 5, 6], 6, 2)
    q = sorted(d for d, r in roles.items() if r.startswith("Q"))
    assert q == [1, 3]  # Tue + Thu with a Sunday long run: never back to back, not the day before
    assert roles[0] == "R"  # Monday after the long run is a recovery run
    assert day_roles([1, 5], 5, 1) == {5: "L", 1: "Q1"}


def test_weekly_km_ceiling():
    plan = generate_plan(PlanRequest(goal="marathon", start_date=START, days_per_week=5, current_weekly_km=30,
                                     level="advanced", max_weekly_km=40))
    for w in plan["weeks"]:
        assert w["target_km"] <= 40
        assert sum(x["distance_km"] for x in _runs(w) if x["type"] != "race") <= 40 * 1.1
    assert plan["max_weekly_km"] == 40


def test_variety_and_hills_not_every_week():
    plan = generate_plan(PlanRequest(goal="half", start_date=START, days_per_week=4, current_weekly_km=30, weeks=16))
    quality = [[x for x in _runs(w) if x["intensity"] != "low" and x["type"] != "long"] for w in plan["weeks"]]
    titles = {x["title"].split(" ")[0] for wk in quality for x in wk}
    assert len({x["type"] for wk in quality for x in wk}) >= 6
    assert len(titles) >= 7
    hill_weeks = [i for i, wk in enumerate(quality) if any(x["type"] == "hills" for x in wk)]
    assert all(b - a >= 2 for a, b in zip(hill_weeks, hill_weeks[1:])), hill_weeks
    # the same quality session never repeats in consecutive weeks
    for a, b in zip(quality, quality[1:]):
        assert not ({x["title"] for x in a} & {x["title"] for x in b} - {""}), (a, b)


def test_no_hills_option():
    plan = generate_plan(PlanRequest(goal="10k", start_date=START, days_per_week=4, current_weekly_km=30, hills=False))
    assert not any(x["type"] == "hills" for w in plan["weeks"] for x in w["workouts"])


def test_seed_changes_formats_but_is_stable():
    def titles(seed):
        p = generate_plan(PlanRequest(goal="10k", start_date=START, days_per_week=5, current_weekly_km=35, seed=seed))
        return [x["title"] for w in p["weeks"] for x in w["workouts"]]
    assert titles(1) == titles(1)
    assert any(titles(s) != titles(1) for s in (2, 3, 4))


def test_strength_is_optional_and_on_chosen_days():
    off = generate_plan(PlanRequest(goal="10k", start_date=START, days_per_week=4))
    assert not any(x["sport"] == "strength" for w in off["weeks"] for x in w["workouts"])
    on = generate_plan(PlanRequest(goal="10k", start_date=START, days_per_week=4, include_strength=True, strength_days=[0, 2]))
    sessions = [x for w in on["weeks"] for x in w["workouts"] if x["sport"] == "strength"]
    assert sessions and {_weekday(x) for x in sessions} <= {0, 2}
    # Wednesday strength comes before Thursday's quality session: lighter, and it says why (Doma 2017)
    assert any("Tomorrow is a key session" in x["description"] for x in sessions if _weekday(x) == 2)
    assert on["strength_days"] == [0, 2]
