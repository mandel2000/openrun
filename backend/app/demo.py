"""Demo account: a shared login with a realistic, generated history so anyone can try OpenRun.

Enabled with OPENRUN_DEMO=1. The login screen then offers "Try the demo", which signs in as the
`demo` user without a password. That account gets:
- a half-marathon plan that started six weeks ago, with past sessions done (or missed) and
  their post-run analysis;
- ~10 months of runs before it, with maps, charts and splits for the recent ones (synthetic GPS
  loop), so records, predictions, load and trends have data;
- four months of HRV, sleep and resting HR, races (a goal, a tune-up and a past result).

Garmin, the AI coach, account changes and uploads are blocked for it (see BLOCKED), and the data
is rebuilt every day (scheduler.tick), so visitors can change anything without breaking it.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import random
import secrets

from sqlalchemy import delete
from sqlmodel import Session, select

from .auth import hash_password
from .db import Activity, ActivityStream, PlannedWorkout, User, engine
from .i18n import _
from .integrations.history_import import best_efforts, make_streams
from .tenancy import TENANT_MODELS, as_user
from .training import workouts as W
from .training.vdot import training_paces

USERNAME = "demo"
CENTER = (40.4153, -3.6845)  # a park loop; any city works
HR_BY_ZONE = {"recovery": 132, "easy": 140, "long": 143, "marathon": 155, "half": 160, "threshold": 166,
              "ten_k": 170, "five_k": 174, "interval": 176, "repetition": 178}
# Non-GET requests a demo session may not make: Garmin, AI chat, account, uploads, notifications.
BLOCKED = ("/api/garmin", "/api/chat", "/api/account/token", "/api/push", "/api/import", "/api/wellness/import",
           "/api/users", "/api/athlete/race-result")
_ids: set[int] = set()


def enabled() -> bool:
    return os.environ.get("OPENRUN_DEMO", "").lower() in ("1", "true", "yes")


def is_demo(uid: int | None) -> bool:
    if not uid:
        return False
    if not _ids:
        with Session(engine) as s:
            _ids.update(u.id for u in s.exec(select(User).where(User.is_demo == True)).all())  # noqa: E712
            _ids.add(0)  # loaded marker
    return uid in _ids


def blocked(method: str, path: str) -> bool:
    if method == "GET":
        return False
    return path.startswith(BLOCKED) or (path.startswith("/api/races/") and "/course" in path)


def demo_user() -> User:
    """The demo account (created and filled on first use)."""
    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == USERNAME)).first()
        if u and not u.is_demo:  # a real account already uses that name: never touch it
            raise RuntimeError("username 'demo' belongs to a real account")
        if not u:
            # random password nobody knows: sessions need one, and the only way in is "Try the demo"
            u = User(username=USERNAME, name="Alex", is_demo=True, password_hash=hash_password(secrets.token_urlsafe(24)),
                     created_at=dt.datetime.now().isoformat(timespec="seconds"))
            s.add(u)
            s.commit()
            s.refresh(u)
        _ids.update({u.id, 0})
    if seeded_on(u.id) != dt.date.today().isoformat():
        reset(u.id)
    return u


def seeded_on(uid: int) -> str | None:
    from . import services as S

    with as_user(uid), Session(engine) as s:
        return S.meta_get(s, "demo").get("date")


def reset(uid: int, today: dt.date | None = None) -> None:
    """Wipe the demo account's data and generate it again relative to today."""
    from . import services as S

    today = today or dt.date.today()
    with Session(engine) as s:
        for m in TENANT_MODELS:
            s.exec(delete(m).where(m.user_id == uid))
        s.commit()
    with as_user(uid), Session(engine) as s:
        _seed(s, today, random.Random(today.toordinal()))
        S.meta_set(s, "demo", {"date": today.isoformat()})


# ---------------------------------------------------------------- generator


def _seed(s: Session, today: dt.date, rng: random.Random) -> None:
    from . import services as S

    S.update_athlete(s, name="Alex", sex="male", age=34, weight_kg=70, max_hr=188, rest_hr=50, lthr=168)
    S.update_settings(s, lat=CENTER[0], lon=CENTER[1], run_hour=8, auto_push=False)
    monday = today - dt.timedelta(days=today.weekday())
    start = monday - dt.timedelta(weeks=6)
    race_day = start + dt.timedelta(weeks=14, days=-1)  # Sunday of week 14

    _history(s, start, rng)
    _wellness(s, today, rng)
    S.create_plan(s, {"goal": "half", "start_date": start.isoformat(), "race_date": race_day.isoformat(),
                      "days_per_week": 4, "long_run_day": 6, "current_weekly_km": 32, "longest_recent_run_km": 15,
                      "level": "intermediate", "recent_race_distance": "10k", "recent_race_time": "47:30",
                      "goal_time": "1:42:00", "name": _("Half marathon in {weeks} weeks", weeks=14)})
    goal = S.add_race(s, _("City Half Marathon"), race_day.isoformat(), 21097.5, "A", goal_time_s=6120)
    S.set_race_course(s, goal["id"], "city-half.gpx", _course_gpx())
    tune = race_day - dt.timedelta(weeks=4)
    S.add_race(s, _("Autumn 10K"), tune.isoformat(), 10000, "B", goal_time_s=2760)
    past = start - dt.timedelta(weeks=8, days=1)
    S.add_race(s, _("Club 10K"), past.isoformat(), 10000, "C", result_time_s=2850)
    _do_plan(s, today, rng)
    S.weekly_review(s, ai=False)


def _history(s: Session, until: dt.date, rng: random.Random) -> None:
    """~10 months of training before the plan: 3-4 runs a week, slowly getting fitter."""
    day = until - dt.timedelta(weeks=44)
    n = 0
    while day < until:
        progress = 1 - (until - day).days / (44 * 7)
        paces = training_paces(41.5 + 3.5 * progress)
        week = [(1, "easy"), (3, "quality"), (6, "long")] + ([(4, "easy")] if rng.random() < 0.6 else [])
        for wd, kind in week:
            d = day + dt.timedelta(days=wd)
            if d >= until or rng.random() < 0.08:
                continue
            km = 6 + 3 * progress
            w = (W.easy_run(paces, km + rng.uniform(-1, 1.5)) if kind == "easy"
                 else W.long_run(paces, 10 + 6 * progress + rng.uniform(-1, 1)) if kind == "long"
                 else rng.choice([W.tempo(paces, 20), W.cruise_intervals(paces, 4, 1000), W.vo2_intervals(paces, 5, 800)]))
            _store(s, w.to_dict(), d, rng, f"h{n}", streams=(until - d).days < 120)
            n += 1
        if day.month in (4, 10) and day.day <= 7:  # a race now and then for the records
            d = day + dt.timedelta(days=5)
            race = W.race(paces, "10k", 10000, "ten_k").to_dict()
            race["title"] = _("Spring 10K") if day.month == 4 else _("Autumn 10K")
            _store(s, race, d, rng, f"r{n}", streams=True, effort=1.0)
            n += 1
        day += dt.timedelta(weeks=1)


def _do_plan(s: Session, today: dt.date, rng: random.Random) -> None:
    """Past plan sessions: done with an activity, except one missed long ago and a key session two days ago."""
    from . import services as S

    past = s.exec(select(PlannedWorkout).where(PlannedWorkout.date < today.isoformat()).order_by(PlannedWorkout.date)).all()
    runs = [p for p in past if p.data.get("sport") == "running"]
    keys = [p for p in runs if p.data.get("intensity") in ("moderate", "high")]
    missed_recent = next((p for p in reversed(keys) if (today - dt.date.fromisoformat(p.date)).days in (1, 2)), None)
    missed_old = runs[len(runs) // 3] if len(runs) > 6 else None
    for i, pw in enumerate(past):
        if pw is missed_recent:
            continue
        if pw is missed_old:
            pw.status, pw.note = "skipped", _("Skipped")
            s.add(pw)
            continue
        if pw.data.get("sport") != "running":
            pw.status = "done"
            s.add(pw)
            _store_strength(s, pw, rng, i)
            continue
        act, laps = _store(s, pw.data, dt.date.fromisoformat(pw.date), rng, f"p{i}", streams=True)
        pw.status, pw.activity_id = "done", act.id
        s.add(pw)
        s.commit()
        S.analyze_activity(s, act, laps)
    s.commit()


def _wellness(s: Session, today: dt.date, rng: random.Random) -> None:
    """HRV around 62 ms with a dip in the last days, so readiness has something to say."""
    from . import services as S

    for i in range(120, -1, -1):
        d = today - dt.timedelta(days=i)
        dip = 6 if 1 <= i <= 5 else 0
        S.upsert_wellness(s, {
            "date": d.isoformat(), "source": "garmin",
            # today low-normal, the days before low: readiness proposes easing off
            "hrv_rmssd": round(60.5 if i == 0 else rng.gauss(62, 4) - dip, 1),
            "rest_hr": round(rng.gauss(50, 1.2) + (2 if dip else 0)),
            "sleep_score": round(min(97, max(45, rng.gauss(80, 7) - (12 if i == 0 else 0)))),
            "sleep_hours": round(min(9.2, max(5, rng.gauss(7.4, 0.6))), 1),
            "body_battery": round(min(100, max(20, rng.gauss(78, 9) - 2 * dip))),
            "training_readiness": round(min(100, max(15, rng.gauss(70, 10) - 3 * dip))),
        })


# ---------------------------------------------------------------- one activity


def _leaf_steps(steps: list[dict]):
    """(step, index) with repeats expanded; index is the pre-order numbering of analysis.step_index_map
    (all repetitions of a step share it, as on a Garmin watch)."""
    index: dict[int, int] = {}

    def number(items: list[dict]) -> None:
        for st in items:
            index[id(st)] = len(index)
            number((st.get("steps") or []) if st.get("kind") == "repeat" else [])

    def expand(items: list[dict]):
        for st in items:
            if st.get("kind") == "repeat":
                for _r in range(st.get("repeat", 1)):
                    yield from expand(st.get("steps") or [])
            else:
                yield st, index[id(st)]

    number(steps)
    yield from expand(steps)


def _course_gpx(total: float = 21097.5) -> bytes:
    """A rolling city half-marathon course (two climbs) as GPX, so the race strategy has a profile."""
    pts, lat, lon = [], CENTER[0] - 0.03, CENTER[1] - 0.04
    for i in range(int(total // 100) + 1):
        d = min(i * 100.0, total)
        heading = 1.2 * math.pi * d / total + 0.5 * math.sin(2 * math.pi * d / 4000)  # a wide arc across town
        ele = 640 + 28 * math.sin(2 * math.pi * d / 9000) + 9 * math.sin(2 * math.pi * d / 2600)
        pts.append(f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>{ele:.1f}</ele></trkpt>')
        lat += 100 * math.cos(heading) / 111320
        lon += 100 * math.sin(heading) / (111320 * math.cos(math.radians(lat)))
    return ('<?xml version="1.0"?><gpx version="1.1" creator="OpenRun demo"><trk><trkseg>'
            + "".join(pts) + "</trkseg></trk></gpx>").encode()


def _position(d: float) -> tuple[float, float, float]:
    """Point on a ~2.8 km park loop at distance d, with gentle rolling elevation."""
    r0, perim = 450.0, 2 * math.pi * 450.0
    th = 2 * math.pi * (d % perim) / perim
    r = r0 * (1 + 0.12 * math.sin(3 * th))
    lat = CENTER[0] + r * math.cos(th) / 111320
    lon = CENTER[1] + r * math.sin(th) / (111320 * math.cos(math.radians(CENTER[0])))
    ele = 655 + 9 * math.sin(2 * math.pi * d / perim) + 3 * math.sin(2 * math.pi * d / 700)
    return lat, lon, ele


def _store(s: Session, w: dict, day: dt.date, rng: random.Random, key: str, streams: bool = False,
           effort: float | None = None) -> tuple[Activity, list[dict]]:
    from . import services as S

    form = effort if effort is not None else rng.uniform(0.985, 1.02)  # <1 = faster than target
    cols: dict[str, list] = {k: [] for k in ("t", "d", "lat", "lon", "ele", "hr", "cad", "speed")}
    raw_laps = []
    t = d = 0.0
    hr = 105.0
    easy = (w.get("steps") or [{}])[0].get("pace_slow") or 360
    for n, (st, idx) in enumerate(_leaf_steps(w.get("steps") or [])):
        pace = ((st["pace_slow"] + st["pace_fast"]) / 2 if st.get("pace_slow") else easy * (1.25 if st.get("kind") == "rest" else 1.12)) * form
        target_hr = HR_BY_ZONE.get(st.get("zone") or "", 128 if st.get("kind") in ("recovery", "rest") else 138)
        dur = st["duration_value"] * pace / 1000 if st.get("duration_type") == "distance" else st.get("duration_value") or 0
        lap_t0, lap_d0, lap_hr = t, d, []
        steps_n = max(1, int(dur / 2))
        for _i in range(steps_n):
            v = 1000 / (pace * rng.uniform(0.97, 1.03))
            t, d = t + dur / steps_n, d + v * dur / steps_n
            hr += (target_hr - hr) * 0.06 + rng.uniform(-0.8, 0.8)
            lat, lon, ele = _position(d)
            for k, val in zip(("t", "d", "lat", "lon", "ele", "hr", "cad", "speed"),
                              (t, d, lat, lon, ele, round(hr), round(150 + 9 * v + rng.uniform(-2, 2)), v)):
                cols[k].append(val)
            lap_hr.append(hr)
        raw_laps.append({"lapIndex": n + 1, "intensityType": {"warmup": "WARMUP", "cooldown": "COOLDOWN", "recovery": "RECOVERY", "rest": "REST"}.get(st.get("kind"), "ACTIVE"),
                         "wktStepIndex": idx, "distance": d - lap_d0, "movingDuration": t - lap_t0,
                         "averageHR": round(sum(lap_hr) / len(lap_hr)), "maxHR": round(max(lap_hr))})
    start = dt.datetime.combine(day, dt.time(7 + rng.randint(0, 2), rng.choice((0, 15, 30, 45))))
    hrs = cols["hr"]
    ele = cols["ele"]
    act = {"external_id": f"demo:{key}", "date": day.isoformat(), "start_time": start.isoformat(sep=" "),
           "name": w.get("title", "").replace("🏁 ", ""), "sport": "running", "source": "demo",
           "distance_m": round(d, 1), "duration_s": round(t), "avg_hr": round(sum(hrs) / len(hrs)), "max_hr": max(hrs),
           "elevation_gain": round(sum(max(0, b - a) for a, b in zip(ele, ele[1:]))), "avg_cadence": round(sum(cols["cad"]) / len(hrs)),
           "training_effect": round(min(5.0, 2.2 + (sum(hrs) / len(hrs) - 135) / 14), 1),
           "best_efforts": best_efforts(cols["t"], cols["d"]), "start_lat": cols["lat"][0], "start_lon": cols["lon"][0]}
    row = S.upsert_activity(s, act)
    if streams:
        s.add(ActivityStream(activity_id=row.id, data=make_streams(cols)))
        s.commit()
    return row, raw_laps


def _store_strength(s: Session, pw: PlannedWorkout, rng: random.Random, i: int) -> None:
    from . import services as S

    t = dt.datetime.combine(dt.date.fromisoformat(pw.date), dt.time(19, 0))
    S.upsert_activity(s, {"external_id": f"demo:s{i}", "date": pw.date, "start_time": t.isoformat(sep=" "),
                          "name": pw.data.get("title"), "sport": "strength_training", "source": "demo",
                          "distance_m": 0, "duration_s": (pw.data.get("duration_min") or 35) * 60,
                          "avg_hr": rng.randint(102, 115), "max_hr": rng.randint(140, 155)})

