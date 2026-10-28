"""Domain services shared by the REST API and the AI coach tools."""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from sqlmodel import Session, select

from .db import Activity, Athlete, Meta, Plan, PlannedWorkout, Race, Wellness
from .integrations.garmin import garmin
from .training import adapt, load, records as R
from .training import workouts as W
from .training.plan import PlanRequest, generate_plan, resolve_vdot
from .training.vdot import RACE_DISTANCES_M, fmt_time, parse_time, race_predictions, training_paces, vdot_from_race


def get_athlete(s: Session) -> Athlete:
    a = s.get(Athlete, 1)
    if not a:
        a = Athlete(id=1)
        s.add(a)
        s.commit()
        s.refresh(a)
    return a


def athlete_profile(s: Session) -> dict:
    a = get_athlete(s)
    out = a.model_dump()
    if a.vdot:
        out["paces"] = training_paces(a.vdot).as_dict()
        out["predictions"] = race_predictions(a.vdot)
    if a.max_hr and a.rest_hr:
        out["hr_zones"] = load.hr_zones(a.max_hr, a.rest_hr, a.lthr)
    return out


def update_athlete(s: Session, **fields) -> dict:
    a = get_athlete(s)
    for k, v in fields.items():
        if v is not None and hasattr(a, k):
            setattr(a, k, v)
    s.add(a)
    s.commit()
    return athlete_profile(s)


def set_race_result(s: Session, distance: str, time: str) -> dict:
    v = vdot_from_race(RACE_DISTANCES_M[distance], parse_time(time))
    update_athlete(s, vdot=round(v, 1), vdot_source=f"race {distance} {time}")
    return athlete_profile(s)


def active_plan(s: Session) -> Plan | None:
    return s.exec(select(Plan).where(Plan.active == True).order_by(Plan.id.desc())).first()  # noqa: E712


def create_plan(s: Session, params: dict) -> dict:
    a = get_athlete(s)
    p = dict(params)
    for k in ("start_date", "race_date"):
        if p.get(k):
            p[k] = dt.date.fromisoformat(p[k])
    if not p.get("start_date"):
        p["start_date"] = dt.date.today() + dt.timedelta(days=1)
    if p.get("goal_time") and not p.get("goal_time_s"):
        p["goal_time_s"] = parse_time(p.pop("goal_time"))
    p.pop("goal_time", None)
    if p.get("recent_race_time") and not p.get("recent_race_time_s"):
        p["recent_race_time_s"] = parse_time(p.pop("recent_race_time"))
    p.pop("recent_race_time", None)
    if not p.get("vdot") and not p.get("recent_race_distance") and a.vdot:
        p["vdot"] = a.vdot
    if not p.get("age") and a.age:
        p["age"] = a.age
    req = PlanRequest(**{k: v for k, v in p.items() if k in PlanRequest.__dataclass_fields__})
    summary = generate_plan(req)
    if not a.vdot or p.get("recent_race_distance"):
        update_athlete(s, vdot=round(resolve_vdot(req), 1), vdot_source="plan setup")

    for old in s.exec(select(Plan).where(Plan.active == True)).all():  # noqa: E712
        old.active = False
        s.add(old)
        for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.plan_id == old.id, PlannedWorkout.status == "planned")).all():
            s.delete(pw)
    plan = Plan(name=summary["name"], goal=summary["goal"], request={k: str(v) for k, v in params.items()},
                summary={k: v for k, v in summary.items() if k != "weeks"})
    s.add(plan)
    s.commit()
    s.refresh(plan)
    for wk in summary["weeks"]:
        for w in wk["workouts"]:
            s.add(PlannedWorkout(plan_id=plan.id, date=w["date"], week=wk["index"], data=w))
    plan.summary = {**plan.summary, "weeks": [{k: v for k, v in wk.items() if k != "workouts"} for wk in summary["weeks"]]}
    s.add(plan)
    s.commit()
    return plan_overview(s)


def plan_overview(s: Session) -> dict | None:
    plan = active_plan(s)
    if not plan:
        return None
    pws = s.exec(select(PlannedWorkout).where(PlannedWorkout.plan_id == plan.id).order_by(PlannedWorkout.date)).all()
    weeks: dict[int, list] = defaultdict(list)
    for pw in pws:
        weeks[pw.week].append(workout_dict(pw))
    meta = {w["index"]: w for w in plan.summary.get("weeks", [])}
    start = dt.date.fromisoformat(plan.summary["start_date"])
    acts = s.exec(select(Activity).where(Activity.sport == "running", Activity.date >= start.isoformat())).all()

    def week_info(i: int) -> dict:
        mon = start + dt.timedelta(weeks=i - 1)
        sun = mon + dt.timedelta(days=6)
        done = sum((a.data.get("distance_m") or 0) for a in acts if mon.isoformat() <= a.date <= sun.isoformat()) / 1000
        planned = sum(w.get("distance_km") or 0 for w in weeks[i] if w.get("sport") == "running" and w["status"] != "skipped")
        return {"start": mon.isoformat(), "end": sun.isoformat(), "done_km": round(done, 1), "planned_km": round(planned, 1)}

    return {
        "id": plan.id, "name": plan.name, "goal": plan.goal,
        **{k: v for k, v in plan.summary.items() if k != "weeks"},
        "weeks": [{**meta.get(i, {"index": i}), **week_info(i), "workouts": weeks[i]} for i in sorted(weeks)],
    }


def workout_dict(pw: PlannedWorkout) -> dict:
    return {"id": pw.id, "week": pw.week, "status": pw.status, "garmin_workout_id": pw.garmin_workout_id,
            "activity_id": pw.activity_id, "note": pw.note, **pw.data, "date": pw.date}


def list_workouts(s: Session, start: str, end: str) -> list[dict]:
    q = select(PlannedWorkout).where(PlannedWorkout.date >= start, PlannedWorkout.date <= end).order_by(PlannedWorkout.date)
    return [workout_dict(pw) for pw in s.exec(q).all()]


def _fill_paces(steps: list[dict], vdot: float) -> list[dict]:
    paces = training_paces(vdot)
    out = []
    for st in steps:
        st = dict(st)
        if st.get("kind") == "repeat":
            st["steps"] = _fill_paces(st.get("steps", []), vdot)
            st["repeat"] = int(st.get("repeat") or 1)
        elif st.get("zone"):
            pr = paces.get(st["zone"])
            st["pace_slow"], st["pace_fast"] = pr.slow, pr.fast
        out.append(st)
    return out


def save_custom_workout(s: Session, date: str, title: str, type: str, steps: list[dict], description: str = "",
                        intensity: str = "moderate", replace_id: int | None = None) -> dict:
    """Validate a workout from structured steps; pace targets are derived from the athlete's VDOT zones."""
    a = get_athlete(s)
    vdot = a.vdot or 40.0
    w = W.Workout.from_dict({"type": type, "title": title, "description": description,
                             "steps": _fill_paces(steps, vdot), "intensity": intensity, "date": date})
    plan = active_plan(s)
    if replace_id:
        pw = s.get(PlannedWorkout, replace_id)
        if not pw:
            raise ValueError(f"workout {replace_id} no existe")
        pw.data = {**w.to_dict(), "phase": pw.data.get("phase", "")}
        pw.date, pw.status = date, "modified"
    else:
        pw = PlannedWorkout(plan_id=plan.id if plan else None, date=date, data=w.to_dict(),
                            week=_week_of(s, plan, date))
    s.add(pw)
    s.commit()
    s.refresh(pw)
    return {**workout_dict(pw), "readable": W.describe_steps(w.steps)}


def _run_km(s: Session, start: dt.date, days: int = 7) -> float:
    ws = list_workouts(s, start.isoformat(), (start + dt.timedelta(days=days - 1)).isoformat())
    return sum(w.get("distance_km") or 0 for w in ws if w.get("sport") == "running" and w["status"] != "skipped")


def add_extra_run(s: Session, date: str, km: float | None = None) -> dict:
    """Add an optional easy run to a week. Extra volume stays at E pace so the 80/20 split holds,
    and we warn when it pushes the week > 10 % above the previous one (Nielsen 2014; Gabbett 2016)."""
    a = get_athlete(s)
    d = dt.date.fromisoformat(date)
    monday = d - dt.timedelta(days=d.weekday())
    week_km = _run_km(s, monday)
    prev_km = _run_km(s, monday - dt.timedelta(days=7))
    km = km or min(max(round(week_km * 0.2), 4), 10)
    w = W.easy_run(training_paces(a.vdot or 40.0), km)
    w.title = f"Rodaje extra {w.distance_km:g} km"
    w.description += " Opcional: añadido por ti fuera del plan base."
    plan = active_plan(s)
    pw = PlannedWorkout(plan_id=plan.id if plan else None, date=date, data={**w.to_dict(), "extra": True},
                        week=_week_of(s, plan, date))
    s.add(pw)
    s.commit()
    s.refresh(pw)
    warnings = []
    same_day = [x for x in list_workouts(s, date, date) if x["id"] != pw.id]
    if same_day:
        warnings.append("Ese día ya tienes otro entreno: doble sesión.")
    new_km = week_km + w.distance_km
    if prev_km and new_km > prev_km * 1.1:
        warnings.append(f"La semana pasa a {new_km:.0f} km (+{(new_km / prev_km - 1) * 100:.0f} % vs la anterior). "
                        "Más de +10 % sube el riesgo de lesión; acórtalo o quítalo en semanas de descarga.")
    nxt = list_workouts(s, (d + dt.timedelta(days=1)).isoformat(), (d + dt.timedelta(days=1)).isoformat())
    if any(x.get("intensity") in ("moderate", "high") or x.get("type") == "long" for x in nxt):
        warnings.append("Mañana tienes sesión clave: mantenlo muy suave.")
    return {**workout_dict(pw), "week_km": round(new_km, 1), "warnings": warnings}


def _week_of(s: Session, plan: Plan | None, date: str) -> int:
    if not plan or not plan.summary.get("start_date"):
        return 0
    start = dt.date.fromisoformat(plan.summary["start_date"])
    return (dt.date.fromisoformat(date) - start).days // 7 + 1


def delete_workout(s: Session, workout_id: int) -> None:
    pw = s.get(PlannedWorkout, workout_id)
    if pw:
        if pw.garmin_workout_id:
            try:
                garmin.delete_workout(pw.garmin_workout_id)
            except Exception:  # noqa: BLE001 - already gone in Connect
                pass
        s.delete(pw)
        s.commit()


def move_workout(s: Session, workout_id: int, new_date: str) -> dict:
    pw = s.get(PlannedWorkout, workout_id)
    if not pw:
        raise ValueError("workout no existe")
    pw.date = new_date
    pw.data = {**pw.data, "date": new_date}
    s.add(pw)
    s.commit()
    if pw.garmin_workout_id:  # re-schedule on the watch (push deletes the old copy)
        push_to_garmin(s, [pw.id])
    return workout_dict(pw)


def push_to_garmin(s: Session, workout_ids: list[int]) -> list[dict]:
    res = []
    for wid in workout_ids:
        pw = s.get(PlannedWorkout, wid)
        if not pw or pw.data.get("sport") != "running":
            res.append({"id": wid, "ok": False, "error": "no es un entreno de carrera"})
            continue
        try:
            if pw.garmin_workout_id:
                try:
                    garmin.delete_workout(pw.garmin_workout_id)
                except Exception:  # noqa: BLE001 - already deleted in Connect
                    pass
            r = garmin.push_workout({**pw.data, "date": pw.date})
            pw.garmin_workout_id = str(r["workout_id"])
            s.add(pw)
            s.commit()
            res.append({"id": wid, "ok": True, "garmin_workout_id": pw.garmin_workout_id})
        except Exception as e:  # noqa: BLE001
            res.append({"id": wid, "ok": False, "error": str(e)})
    return res


def push_upcoming(s: Session, days: int = 7) -> list[dict]:
    today = dt.date.today()
    ws = list_workouts(s, today.isoformat(), (today + dt.timedelta(days=days)).isoformat())
    return push_to_garmin(s, [w["id"] for w in ws if w["sport"] == "running" and w["status"] != "done"])


# ---------------------------------------------------------------- data ingest


def upsert_activity(s: Session, act: dict) -> Activity:
    a = get_athlete(s)
    existing = s.exec(select(Activity).where(Activity.external_id == act["external_id"])).first()
    row = existing or Activity(external_id=act["external_id"], date=act["date"])
    row.sport, row.data, row.date = act.get("sport", "running"), act, act["date"]
    row.trimp = load.trimp((act.get("duration_s") or 0) / 60, act.get("avg_hr") or 0, a.rest_hr or 55, a.max_hr or 190, a.sex)
    s.add(row)
    s.commit()
    s.refresh(row)
    _match_planned(s, row)
    return row


def _match_planned(s: Session, act: Activity) -> None:
    if act.sport != "running":
        return
    pw = s.exec(select(PlannedWorkout).where(PlannedWorkout.date == act.date, PlannedWorkout.status.in_(["planned", "modified"]))).all()
    pw = [p for p in pw if p.data.get("sport") == "running"]
    if pw:
        pw[0].status, pw[0].activity_id = "done", act.id
        s.add(pw[0])
        s.commit()


def upsert_wellness(s: Session, row: dict) -> None:
    w = s.exec(select(Wellness).where(Wellness.date == row["date"], Wellness.source == row.get("source", "garmin"))).first()
    w = w or Wellness(date=row["date"], source=row.get("source", "garmin"))
    for k in ("hrv_rmssd", "rest_hr", "sleep_score", "sleep_hours"):
        if row.get(k) is not None:
            setattr(w, k, row[k])
    w.extra = {**(w.extra or {}), **{k: v for k, v in row.items() if k not in ("date", "source", "hrv_rmssd", "rest_hr", "sleep_score", "sleep_hours")}}
    s.add(w)
    s.commit()


def meta_get(s: Session, key: str) -> dict:
    m = s.get(Meta, key)
    return m.value if m else {}


def meta_set(s: Session, key: str, value: dict) -> None:
    m = s.get(Meta, key) or Meta(key=key)
    m.value = value
    s.add(m)
    s.commit()


def sync_garmin(s: Session, days: int = 14, full: bool = False) -> dict:
    """Pull activities (last `days`, or the whole history when `full`), wellness and watch metrics."""
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    acts = garmin.fetch_all_activities() if full or not s.exec(select(Activity)).first() else garmin.fetch_activities(start, end)
    for a in acts:
        upsert_activity(s, a)
    n_w = 0
    for i in range(min(days, 30) + 1):
        upsert_wellness(s, garmin.fetch_wellness(end - dt.timedelta(days=i)))
        n_w += 1
    metrics = garmin.fetch_profile_metrics()
    meta_set(s, "garmin_metrics", {**metrics, "synced_at": dt.datetime.now().isoformat(timespec="seconds")})
    analyzed = analyze_recent(s, min(days, 30))
    try:
        meta_set(s, "garmin_prs", garmin.fetch_personal_records())
    except Exception:  # noqa: BLE001 - PR endpoint is optional
        pass
    if metrics.get("lthr"):
        update_athlete(s, lthr=int(metrics["lthr"]))
    rhr = [w.rest_hr for w in s.exec(select(Wellness).where(Wellness.rest_hr != None)).all()]  # noqa: E711
    a = get_athlete(s)
    if rhr and not a.rest_hr:
        update_athlete(s, rest_hr=int(sorted(rhr)[len(rhr) // 2]))
    return {"activities": len(acts), "wellness_days": n_w, "analyzed": analyzed, "metrics": metrics}


# ---------------------------------------------------------------- analytics


def wellness_rows(s: Session, days: int = 90) -> list[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = s.exec(select(Wellness).where(Wellness.date >= cutoff).order_by(Wellness.date)).all()
    merged: dict[str, dict] = {}
    # Prefer chest/arm strap BLE readings > Garmin > Zepp for HRV when several exist for a day.
    prio = {"ble": 3, "garmin": 2, "zepp": 1}
    for r in sorted(rows, key=lambda r: prio.get(r.source, 0)):
        m = merged.setdefault(r.date, {"date": r.date})
        for k in ("hrv_rmssd", "rest_hr", "sleep_score", "sleep_hours"):
            if getattr(r, k) is not None:
                m[k] = getattr(r, k)
                m[f"{k}_source"] = r.source
        m.update({k: v for k, v in (r.extra or {}).items() if v is not None})
    return [merged[d] for d in sorted(merged)]


def readiness_today(s: Session) -> dict:
    return load.readiness(wellness_rows(s, 70)).to_dict()


def training_load(s: Session, days: int = 90) -> dict:
    daily: dict[str, float] = defaultdict(float)
    for a in s.exec(select(Activity)).all():
        daily[a.date] += a.trimp
    series = load.load_series(daily, days)
    return {"series": series, "today": series[-1] if series else None}


def recent_activities(s: Session, days: int = 28) -> list[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = s.exec(select(Activity).where(Activity.date >= cutoff).order_by(Activity.date.desc())).all()
    out = []
    for r in rows:
        d = dict(r.data)
        d["id"], d["trimp"] = r.id, round(r.trimp, 1)
        if d.get("analysis"):  # laps stay in /activities/{id}/analysis; keep lists and the coach light
            d["analysis"] = {k: d["analysis"].get(k) for k in ("verdict", "on_target_pct", "avg_dev_pct", "work_hr", "notes", "planned_title")}
        if d.get("distance_m") and d.get("duration_s"):
            d["pace_s_km"] = round(d["duration_s"] / (d["distance_m"] / 1000))
        out.append(d)
    return out


def _activity_rows(s: Session) -> list[dict]:
    return [{**r.data, "id": r.id, "date": r.date, "sport": r.sport} for r in s.exec(select(Activity)).all()]


def personal_records(s: Session) -> dict:
    out = R.records(_activity_rows(s))
    # Garmin's own all-time PRs may come from activities older than the synced history
    for k, g in meta_get(s, "garmin_prs").items():
        cur = out["all"].get(k)
        if g.get("time_s") and (cur is None or g["time_s"] < cur["time_s"] - 0.5):
            out["all"][k] = {"time_s": g["time_s"], "time": fmt_time(g["time_s"]), "approx": False,
                             "pace": fmt_time(g["time_s"] / (R.PR_DISTANCES[k] / 1000)), "date": g.get("date"),
                             "name": g.get("name"), "activity_id": None, "source": "garmin"}
    acts = s.exec(select(Activity)).all()
    first = min((a.date for a in acts), default=None)
    return {"records": out, "distances": list(R.PR_DISTANCES), "labels": R.LABEL, "history_since": first,
            "n_activities": len(acts)}


def race_time_predictions(s: Session) -> dict:
    acts = _activity_rows(s)
    fe = fitness_estimate(s)
    p = R.predictions(acts, meta_get(s, "garmin_metrics").get("race_predictions"), fe["vdot"] if fe else None)
    a = get_athlete(s)
    p["current_vdot"] = a.vdot
    p["trend"] = R.vdot_trend(acts)
    best = p.get("best_effort_vdot")
    # Pace insight (like Runna): suggest re-pacing when recent efforts disagree with plan VDOT by >= 1
    p["suggest_vdot"] = best if best and a.vdot and abs(best - a.vdot) >= 1.0 else None
    return p


def fitness_estimate(s: Session) -> dict | None:
    a = get_athlete(s)
    if not (a.max_hr and a.rest_hr):
        return None
    return load.estimate_vdot([r.data for r in s.exec(select(Activity)).all()], a.rest_hr, a.max_hr)


def adapt_today(s: Session, date: str | None = None) -> dict:
    date = date or dt.date.today().isoformat()
    r = readiness_today(s)
    a = get_athlete(s)
    changes = []
    for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == date, PlannedWorkout.status == "planned")).all():
        new, msg = adapt.adjust_for_readiness(pw.data, r["status"], a.vdot or 40)
        if new is not pw.data:
            pw.data, pw.status, pw.note = {**pw.data, **new}, "modified", msg
            s.add(pw)
            changes.append({"id": pw.id, "title": new["title"], "reason": msg})
    s.commit()
    # Replace the copy on the watch (push deletes the old Garmin workout first)
    on_watch = [c["id"] for c in changes if s.get(PlannedWorkout, c["id"]).garmin_workout_id]
    if on_watch:
        push_to_garmin(s, on_watch)
    return {"readiness": r, "changes": changes}


def not_feeling_well(s: Session, days: int, mode: str = "reduce") -> list[dict]:
    a = get_athlete(s)
    today = dt.date.today()
    pws = s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= today.isoformat(),
                                              PlannedWorkout.date < (today + dt.timedelta(days=days)).isoformat(),
                                              PlannedWorkout.status == "planned")).all()
    new = adapt.deload_workouts([p.data for p in pws], a.vdot or 40, mode)
    for pw, nd in zip(pws, new):
        pw.data, pw.status = {**pw.data, **nd}, "modified"
        pw.note = "Ajustado: 'no me encuentro al 100%'"
        s.add(pw)
    s.commit()
    on_watch = [p.id for p in pws if p.garmin_workout_id and p.data.get("sport") == "running"]
    if on_watch:
        push_to_garmin(s, on_watch)
    return [workout_dict(p) for p in pws]


def recalibrate_paces(s: Session, new_vdot: float, source: str) -> dict:
    """Update VDOT and re-pace all future planned workouts (like Runna's pace insights)."""
    update_athlete(s, vdot=round(new_vdot, 1), vdot_source=source)
    today = dt.date.today().isoformat()
    n, to_push = 0, []
    for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= today, PlannedWorkout.status.in_(["planned", "modified"]))).all():
        pw.data = {k: v for k, v in adapt.repace_workout(pw.data, new_vdot).items() if k != "_heat"}  # heat re-applied next run
        if pw.garmin_workout_id:
            to_push.append(pw.id)
        s.add(pw)
        n += 1
    s.commit()
    # Workouts already on the watch get replaced (push_to_garmin deletes the old copy first)
    pushed = push_to_garmin(s, to_push) if to_push else []
    return {"vdot": round(new_vdot, 1), "workouts_updated": n, "garmin_updated": sum(1 for r in pushed if r["ok"]),
            "paces": training_paces(new_vdot).as_dict()}


# ---------------------------------------------------------------- races during the build


def _zone_for(distance_m: float) -> str:
    return min((("five_k", 5000), ("ten_k", 10000), ("half", 21097.5), ("marathon", 42195)),
               key=lambda z: abs(math.log(distance_m / z[1])))[0]


def race_dict(r: Race) -> dict:
    d = r.model_dump()
    d["days_to_go"] = (dt.date.fromisoformat(r.date) - dt.date.today()).days
    return d


def _soften(pw: PlannedWorkout, vdot: float, note: str, mode: str) -> None:
    """Keep the original so deleting the race restores it."""
    if pw.data.get("sport") != "running" or pw.data.get("type") == "race":
        return
    km = pw.data.get("distance_km") or 6
    paces = training_paces(vdot)
    if mode == "shakeout":
        w = W.shakeout(paces)
    elif mode == "recovery":
        w = W.recovery_run(paces, max(4, km * 0.6))
    else:  # quality -> easy (+ strides keeps neuromuscular sharpness)
        w = W.easy_with_strides(paces, max(4, km * 0.7)) if pw.data.get("intensity") != "low" else W.easy_run(paces, max(4, km * 0.8))
    pw.data = {**w.to_dict(), "phase": pw.data.get("phase", ""), "_orig": pw.data.get("_orig") or pw.data}
    pw.status, pw.note = "modified", note


def _resync_garmin(s: Session, pws: list[PlannedWorkout]) -> None:
    """Keep the watch calendar consistent with workouts changed by race adjustments."""
    for pw in pws:
        if not pw.garmin_workout_id:
            continue
        if pw.status == "skipped":
            try:
                garmin.delete_workout(pw.garmin_workout_id)
            except Exception:  # noqa: BLE001
                pass
            pw.garmin_workout_id = None
            s.add(pw)
        else:
            push_to_garmin(s, [pw.id])
    s.commit()


def apply_race(s: Session, r: Race) -> dict:
    """Fit a race into the active plan.

    B (tune-up): mini-taper — quality sessions in the 3 days before become easy + strides, the day
    before is a shake-out; afterwards ~1 easy day per 3 km raced without quality (Daniels), capped at 7.
    C (training race): run it as a hard workout; only the day after becomes recovery.
    A (goal race): the plan should be generated around it (race_date) — return a suggestion.
    The race replaces whatever was planned that day (Mujika & Padilla 2003; Bosquet 2007 for taper logic).
    """
    a = get_athlete(s)
    vdot = a.vdot or 40.0
    plan = active_plan(s)
    changes: list[str] = []
    touched: list[PlannedWorkout] = []
    note = f"Ajustado por carrera: {r.name}"
    d = dt.date.fromisoformat(r.date)
    dist = r.distance_m or 10000

    for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == r.date)).all():
        if pw.data.get("sport") == "running" and pw.data.get("race_id") != r.id:
            pw.data = {**pw.data, "_orig": pw.data.get("_orig") or dict(pw.data)}
            pw.status, pw.note = "skipped", f"Sustituido por {r.name}"
            s.add(pw)
            touched.append(pw)
            changes.append(f"{pw.date}: {pw.data.get('title')} → sustituido por la carrera")

    w = W.race(training_paces(vdot), "", dist, _zone_for(dist))
    w.title = f"🏁 {r.name}" + (" (C · a ritmo de entreno)" if r.priority == "C" else "")
    if r.priority == "C":
        w.intensity = "moderate"
        w.description = "Carrera de entreno: esfuerzo controlado (umbral–ritmo 10K), sin vaciarte. Cuenta como sesión de calidad."
    pw = PlannedWorkout(plan_id=plan.id if plan else None, date=r.date, week=_week_of(s, plan, r.date),
                        data={**w.to_dict(), "race_id": r.id, "phase": "race"})
    s.add(pw)

    if r.priority == "B":
        for i in (1, 2, 3):
            day = (d - dt.timedelta(days=i)).isoformat()
            for x in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == day, PlannedWorkout.status.in_(["planned", "modified"]))).all():
                if i == 1 and x.data.get("sport") == "running":
                    _soften(x, vdot, note, "shakeout")
                    touched.append(x)
                    changes.append(f"{day}: activación pre-carrera")
                elif x.data.get("intensity") in ("moderate", "high") or x.data.get("type") == "long":
                    _soften(x, vdot, note, "easy")
                    touched.append(x)
                    changes.append(f"{day}: calidad → suave + progresivos")
    rec_days = 1 if r.priority == "C" else min(7, max(2, round(dist / 3000)))
    for i in range(1, rec_days + 1):
        day = (d + dt.timedelta(days=i)).isoformat()
        for x in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == day, PlannedWorkout.status.in_(["planned", "modified"]))).all():
            if x.data.get("sport") == "running" and (i == 1 or x.data.get("intensity") in ("moderate", "high") or x.data.get("type") == "long"):
                _soften(x, vdot, note, "recovery" if i == 1 else "easy")
                touched.append(x)
                changes.append(f"{day}: {'regenerativo' if i == 1 else 'calidad → suave'} (recuperación post-carrera)")
    s.commit()
    _resync_garmin(s, touched)
    suggestion = None
    if r.priority == "A" and (not plan or plan.summary.get("race_date") != r.date):
        suggestion = "Es tu carrera objetivo: genera un plan con esta fecha de carrera para periodizar y afinar hacia ella."
    return {"changes": changes, "recovery_days": rec_days, "suggestion": suggestion}


def _restore_race_changes(s: Session, r: Race) -> None:
    note = f"Ajustado por carrera: {r.name}"
    restored: list[PlannedWorkout] = []
    for pw in s.exec(select(PlannedWorkout)).all():
        if pw.data.get("race_id") == r.id:
            if pw.garmin_workout_id:
                try:
                    garmin.delete_workout(pw.garmin_workout_id)
                except Exception:  # noqa: BLE001
                    pass
            s.delete(pw)
        elif (pw.note == note or pw.note == f"Sustituido por {r.name}") and pw.data.get("_orig"):
            pw.data, pw.status, pw.note = pw.data["_orig"], "planned", None
            s.add(pw)
            restored.append(pw)
    s.commit()
    _resync_garmin(s, restored)


def list_races(s: Session) -> list[dict]:
    return [race_dict(r) for r in s.exec(select(Race).order_by(Race.date)).all()]


def add_race(s: Session, name: str, date: str, distance_m: float | None = None, priority: str = "B", **extra) -> dict:
    if priority not in ("A", "B", "C"):
        raise ValueError("prioridad A, B o C")
    r = Race(name=name, date=date, distance_m=distance_m, priority=priority,
             **{k: v for k, v in extra.items() if k in Race.model_fields and v is not None})
    s.add(r)
    s.commit()
    s.refresh(r)
    applied = apply_race(s, r) if dt.date.fromisoformat(date) >= dt.date.today() else {"changes": []}
    return {**race_dict(r), **applied}


def update_race(s: Session, race_id: int, **fields) -> dict:
    r = s.get(Race, race_id)
    if not r:
        raise ValueError("carrera no existe")
    _restore_race_changes(s, r)
    for k, v in fields.items():
        if k in Race.model_fields and k != "id" and v is not None:
            setattr(r, k, v)
    s.add(r)
    s.commit()
    applied = apply_race(s, r) if dt.date.fromisoformat(r.date) >= dt.date.today() else {"changes": []}
    return {**race_dict(r), **applied}


def delete_race(s: Session, race_id: int) -> None:
    r = s.get(Race, race_id)
    if r:
        _restore_race_changes(s, r)
        s.delete(r)
        s.commit()


# ---------------------------------------------------------------- history import (Strava export / FIT / GPX / TCX)

IMPORT_JOBS: dict[str, dict] = {}


def _is_duplicate(index: list[tuple[dt.date, float, float]], a: dict) -> bool:
    """Same run already stored (e.g. from Garmin): date ±1 day, distance ±3 %, duration ±5 %.
    Timezone-agnostic on purpose: sources disagree on local vs UTC start times."""
    d = dt.date.fromisoformat(a["date"])
    dist, dur = a.get("distance_m") or 0, a.get("duration_s") or 0
    for d2, dist2, dur2 in index:
        if abs((d - d2).days) <= 1 and dist2 and abs(dist - dist2) <= 0.03 * dist2 and (not dur2 or abs(dur - dur2) <= 0.05 * dur2):
            return True
    return False


def import_history(s: Session, files: list[tuple[str, object]], progress=None) -> dict:
    from .integrations.history_import import activities_from_upload

    index = [(dt.date.fromisoformat(r.date), r.data.get("distance_m") or 0, r.data.get("duration_s") or 0)
             for r in s.exec(select(Activity).where(Activity.sport == "running")).all()]
    known = {r.external_id for r in s.exec(select(Activity)).all()}
    stats = {"imported": 0, "duplicates": 0, "with_efforts": 0, "oldest": None, "newest": None}
    for fi, (name, source) in enumerate(files):
        def prog(done: int, total: int, fi=fi) -> None:
            if progress:
                progress(fi, len(files), done, total, stats)

        for a in activities_from_upload(name, source, prog):
            if a.get("sport") != "running":
                continue
            if a["external_id"] in known or _is_duplicate(index, a):
                stats["duplicates"] += 1
                continue
            upsert_activity(s, a)
            known.add(a["external_id"])
            index.append((dt.date.fromisoformat(a["date"]), a.get("distance_m") or 0, a.get("duration_s") or 0))
            stats["imported"] += 1
            stats["with_efforts"] += bool(a.get("best_efforts"))
            stats["oldest"] = min(filter(None, [stats["oldest"], a["date"]]))
            stats["newest"] = max(filter(None, [stats["newest"], a["date"]]))
    return stats


def start_import_job(files: list[tuple[str, str]], cleanup: list[str]) -> str:
    """Run import_history in a background thread; files are (original name, temp path)."""
    import os
    import threading
    import uuid

    from .db import engine

    job_id = uuid.uuid4().hex[:12]
    job = IMPORT_JOBS[job_id] = {"id": job_id, "state": "running", "file": 0, "files": len(files), "done": 0, "total": 0,
                                 "stats": {}, "error": None}

    def progress(fi, nf, done, total, stats):
        job.update(file=fi + 1, files=nf, done=done, total=total, stats=dict(stats))

    def run():
        try:
            with Session(engine) as s:
                job["stats"] = import_history(s, files, progress)
            job["state"] = "done"
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            job.update(state="error", error=str(e))
        finally:
            for p in cleanup:
                try:
                    os.remove(p)
                except OSError:
                    pass

    threading.Thread(target=run, daemon=True).start()
    return job_id


# ---------------------------------------------------------------- settings

DEFAULT_SETTINGS = {
    "auto_sync": True,       # daily routine at sync_time
    "sync_time": "06:30",
    "auto_adapt": True,      # adjust today's session to readiness
    "auto_push": True,       # keep the next 7 days on the watch
    "auto_pace": True,       # apply pace insights automatically (VDOT ±0.5)
    "heat_adjust": True,     # slow pace targets in heat
    "run_hour": 8,           # usual training hour (for the weather forecast)
    "lat": None, "lon": None,
}


def get_settings(s: Session) -> dict:
    return {**DEFAULT_SETTINGS, **meta_get(s, "settings")}


def update_settings(s: Session, **kw) -> dict:
    cur = get_settings(s)
    cur.update({k: v for k, v in kw.items() if k in DEFAULT_SETTINGS})
    meta_set(s, "settings", cur)
    return cur


def _location(s: Session) -> tuple[float, float] | None:
    st = get_settings(s)
    if st.get("lat") is not None and st.get("lon") is not None:
        return float(st["lat"]), float(st["lon"])
    for a in s.exec(select(Activity).where(Activity.sport == "running").order_by(Activity.date.desc())).all():
        if a.data.get("start_lat") is not None:
            return a.data["start_lat"], a.data["start_lon"]
    return None


# ---------------------------------------------------------------- post-workout analysis & pace insights

from .training import analysis as AN  # noqa: E402
from .training import heat as HEAT  # noqa: E402


def analyze_activity(s: Session, act: Activity, laps_raw: list[dict] | None = None) -> dict | None:
    if act.sport != "running" or not act.external_id.startswith("garmin:"):
        return None
    if laps_raw is None:
        laps_raw = garmin.fetch_laps(act.external_id)
    pw = s.exec(select(PlannedWorkout).where(PlannedWorkout.activity_id == act.id)).first()
    res = AN.analyze(AN.normalize_laps(laps_raw), pw.data if pw else None, get_athlete(s).lthr)
    res.update(planned_id=pw.id if pw else None, planned_title=pw.data.get("title") if pw else None,
               analyzed_at=dt.datetime.now().isoformat(timespec="seconds"))
    act.data = {**act.data, "analysis": res}
    s.add(act)
    s.commit()
    return res


def analyze_recent(s: Session, days: int = 14) -> int:
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    n = 0
    for act in s.exec(select(Activity).where(Activity.sport == "running", Activity.date >= cutoff)).all():
        if "analysis" in act.data or not act.external_id.startswith("garmin:"):
            continue
        try:
            analyze_activity(s, act)
            n += 1
        except Exception:  # noqa: BLE001 - analysis is best effort
            pass
    return n


def pace_insights(s: Session, apply: bool | None = None) -> dict:
    """Evaluate recent quality sessions; apply the change if auto_pace (or apply=True)."""
    a = get_athlete(s)
    log = meta_get(s, "pace_log").get("items", [])
    sessions = [{"date": x.date, "verdict": x.data["analysis"].get("verdict")}
                for x in s.exec(select(Activity).where(Activity.sport == "running")).all()
                if (x.data.get("analysis") or {}).get("verdict")]
    plan = active_plan(s)
    goal = plan.summary.get("race_date") if plan else None
    goal = goal or next((r.date for r in s.exec(select(Race).where(Race.priority == "A")).all() if r.date >= dt.date.today().isoformat()), None)
    prop = AN.pace_insight(sessions, dt.date.today(), log[-1]["date"] if log else None, goal, a.vdot or 40.0) if a.vdot else None
    applied = None
    if prop and (apply if apply is not None else get_settings(s)["auto_pace"]):
        res = recalibrate_paces(s, prop["to"], f"pace insight: {prop['reason']}")
        applied = {**prop, "date": dt.date.today().isoformat(), "workouts_updated": res["workouts_updated"],
                   "garmin_updated": res.get("garmin_updated", 0)}
        log.append(applied)
        meta_set(s, "pace_log", {"items": log[-20:]})
        prop = None
    return {"pending": prop, "applied": applied, "log": log[-10:], "sessions": sorted(sessions, key=lambda x: x["date"])[-6:]}


# ---------------------------------------------------------------- heat

def weather_for(s: Session, date: str) -> dict | None:
    loc = _location(s)
    if not loc:
        return None
    hour = int(get_settings(s)["run_hour"])
    w = HEAT.at(HEAT.forecast(*loc), date, hour)
    if not w or w["temp"] is None or w["dew"] is None:
        return None
    pct, sum_f = HEAT.slowdown_pct(w["temp"], w["dew"])
    return {**w, "date": date, "hour": hour, "pct": pct, "sum_f": sum_f, "too_hot": sum_f > HEAT.TOO_HOT, "lat": loc[0], "lon": loc[1]}


def apply_heat(s: Session, days: int = 2) -> list[dict]:
    """Slow pace targets of the next `days` running workouts by the forecast heat; restore when it cools."""
    changes = []
    today = dt.date.today()
    for i in range(days):
        date = (today + dt.timedelta(days=i)).isoformat()
        try:
            w = weather_for(s, date)
        except Exception:  # noqa: BLE001 - no forecast, no change
            w = None
        if not w:
            continue
        for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == date, PlannedWorkout.status.in_(["planned", "modified"]))).all():
            if pw.data.get("sport") != "running":
                continue
            h = pw.data.get("_heat")
            base = h["orig_steps"] if h else pw.data["steps"]
            if w["pct"] >= 1:
                if h and h["pct"] == w["pct"]:
                    continue
                note = f"Ritmos +{w['pct']:g} % por calor ({w['temp']:.0f} °C, rocío {w['dew']:.0f} °C a las {w['hour']}h). Mantén el esfuerzo, no el ritmo."
                if w["too_hot"] and pw.data.get("intensity") in ("moderate", "high"):
                    note += " Calor extremo: mejor hazla en cinta, a primera hora o cámbiala por suave."
                pw.data = {**pw.data, "steps": HEAT.scale_steps(base, w["pct"]),
                           "_heat": {"pct": w["pct"], "temp": w["temp"], "dew": w["dew"], "orig_steps": base}}
                pw.note, pw.status = note, "modified"
                changes.append({"id": pw.id, "date": date, "title": pw.data.get("title"), "pct": w["pct"]})
            elif h:
                pw.data = {k: v for k, v in pw.data.items() if k != "_heat"} | {"steps": base}
                pw.note = None
                changes.append({"id": pw.id, "date": date, "title": pw.data.get("title"), "pct": 0})
            s.add(pw)
    s.commit()
    return changes


# ---------------------------------------------------------------- watch sync & daily routine

def _hash(data: dict) -> str:
    import hashlib
    import json
    keep = {k: v for k, v in data.items() if k in ("title", "steps", "description", "date")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:16]


def push_changed(s: Session, days: int = 7) -> list[dict]:
    """Push only workouts that are new or changed since their last push (no daily churn on the watch)."""
    today = dt.date.today()
    hashes = meta_get(s, "push_hashes")
    ids = []
    for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= today.isoformat(),
                                                   PlannedWorkout.date <= (today + dt.timedelta(days=days)).isoformat(),
                                                   PlannedWorkout.status.in_(["planned", "modified"]))).all():
        if pw.data.get("sport") == "running" and (not pw.garmin_workout_id or hashes.get(str(pw.id)) != _hash({**pw.data, "date": pw.date})):
            ids.append(pw.id)
    res = push_to_garmin(s, ids) if ids else []
    for r in res:
        if r["ok"]:
            pw = s.get(PlannedWorkout, r["id"])
            hashes[str(r["id"])] = _hash({**pw.data, "date": pw.date})
    meta_set(s, "push_hashes", hashes)
    return res


def daily_routine(s: Session, force: bool = False) -> dict:
    """Morning routine: sync → analyse → pace insights → heat → readiness → push next 7 days."""
    st = get_settings(s)
    log: dict = {"at": dt.datetime.now().isoformat(timespec="seconds"), "steps": []}

    def step(name: str, fn):
        try:
            out = fn()
            log["steps"].append({"step": name, "ok": True, "result": out})
        except Exception as e:  # noqa: BLE001 - keep going, report
            log["steps"].append({"step": name, "ok": False, "error": str(e)})

    connected = garmin.status().get("connected")
    if connected:
        step("sync", lambda: {k: v for k, v in sync_garmin(s, 3).items() if k != "metrics"})
    step("análisis", lambda: {"analizadas": analyze_recent(s)})
    step("ritmos", lambda: (lambda r: {"aplicado": r["applied"], "pendiente": r["pending"]})(pace_insights(s)))
    if st["heat_adjust"]:
        step("calor", lambda: apply_heat(s))
    if st["auto_adapt"]:
        step("readiness", lambda: adapt_today(s)["changes"])
    if connected and st["auto_push"]:
        step("reloj", lambda: (lambda r: {"enviados": sum(1 for x in r if x["ok"]), "errores": [x.get("error") for x in r if not x["ok"]]})(push_changed(s)))
    step("copia", backup_db)
    hist = meta_get(s, "daily_log").get("items", [])
    meta_set(s, "daily_log", {"items": (hist + [log])[-14:], "last_date": dt.date.today().isoformat()})
    return log


def backup_db(keep: int = 14) -> dict | None:
    """Consistent SQLite snapshot (online backup API) into <data>/backups, keeping the last `keep`."""
    import sqlite3

    from .db import DB_PATH, DB_URL

    if DB_URL:
        return None  # external databases have their own backups
    folder = DB_PATH.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"openrun-{dt.date.today().isoformat()}.db"
    src = sqlite3.connect(DB_PATH)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    old = sorted(folder.glob("openrun-*.db"))[:-keep]
    for f in old:
        f.unlink()
    return {"file": dest.name, "kept": min(keep, len(list(folder.glob('openrun-*.db'))))}
