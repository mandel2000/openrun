"""Domain services shared by the REST API and the AI coach tools."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from collections import defaultdict

from sqlmodel import Session, select

from . import i18n
from .db import Activity, Athlete, Meta, Plan, PlannedWorkout, Race, Wellness, engine
from .i18n import N_, _, language_name
from .integrations.garmin import garmin
from .training import adapt, load
from .training import records as R
from .training import workouts as W
from .training.plan import PlanRequest, generate_plan, resolve_vdot
from .training.vdot import RACE_DISTANCES_M, fmt_time, parse_time, race_predictions, training_paces, vdot_from_race


def get_athlete(s: Session) -> Athlete:
    a = s.exec(select(Athlete)).first()
    if not a:
        a = Athlete()
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
    d = {"id": pw.id, "week": pw.week, "status": pw.status, "garmin_workout_id": pw.garmin_workout_id,
         "activity_id": pw.activity_id, "note": pw.note, **pw.data, "date": pw.date}
    if d.get("sport") == "strength" and not d.get("exercises"):  # plans made before structured sessions
        from .training.strength import focus_for_title, session
        d["exercises"] = session(focus_for_title(d.get("title", "")))["exercises"]
    return d


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
            raise ValueError(f"workout {replace_id} does not exist")
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
    w.title = _("Extra run {km} km", km=f"{w.distance_km:g}")
    w.description += " " + _("Optional: added by you outside the base plan.")
    plan = active_plan(s)
    pw = PlannedWorkout(plan_id=plan.id if plan else None, date=date, data={**w.to_dict(), "extra": True},
                        week=_week_of(s, plan, date))
    s.add(pw)
    s.commit()
    s.refresh(pw)
    warnings = []
    same_day = [x for x in list_workouts(s, date, date) if x["id"] != pw.id]
    if same_day:
        warnings.append(_("You already have a workout that day: double session."))
    new_km = week_km + w.distance_km
    if prev_km and new_km > prev_km * 1.1:
        warnings.append(_("The week goes up to {km} km (+{pct}% vs the previous one). More than +10% raises the injury "
                          "risk; shorten or drop it in recovery weeks.", km=f"{new_km:.0f}", pct=f"{(new_km / prev_km - 1) * 100:.0f}"))
    nxt = list_workouts(s, (d + dt.timedelta(days=1)).isoformat(), (d + dt.timedelta(days=1)).isoformat())
    if any(x.get("intensity") in ("moderate", "high") or x.get("type") == "long" for x in nxt):
        warnings.append(_("Tomorrow is a key session: keep it very easy."))
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


def move_workout(s: Session, workout_id: int, new_date: str, swap: bool = False) -> dict:
    """Move a session to another day. With `swap`, sessions already planned that day take the
    moved one's place (drag & drop in the plan). Warns when two hard days end up back to back."""
    pw = s.get(PlannedWorkout, workout_id)
    if not pw:
        raise ValueError(_("workout does not exist"))
    if pw.status == "done":
        raise ValueError(_("That workout is already done"))
    dt.date.fromisoformat(new_date)
    if new_date < dt.date.today().isoformat():
        raise ValueError(_("Can't move it to a past day"))
    old_date = pw.date
    if old_date == new_date:
        return {**workout_dict(pw), "moved": [], "warnings": []}
    others = [x for x in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == new_date,
                                                             PlannedWorkout.status.in_(["planned", "modified"]))).all()
              if x.id != pw.id] if swap else []
    changed = [pw]
    for x in [pw] + others:
        d = new_date if x is pw else old_date
        x.date = d
        x.data = {**x.data, "date": d}
        s.add(x)
        if x is not pw:
            changed.append(x)
    s.commit()
    on_watch = [x.id for x in changed if x.garmin_workout_id]
    pushed = push_to_garmin(s, on_watch) if on_watch else []  # re-schedule on the watch (push deletes the old copy)
    return {**workout_dict(pw), "moved": [{"id": x.id, "date": x.date, "title": x.data.get("title")} for x in changed],
            "warnings": _hard_day_warnings(s, {old_date, new_date}),
            "watch": {"ok": sum(1 for r in pushed if r.get("ok")), "failed": sum(1 for r in pushed if not r.get("ok"))}}


def _is_hard(data: dict) -> bool:
    return data.get("sport") == "running" and (data.get("intensity") in ("high", "moderate") or data.get("type") in ("long", "race"))


def _hard_day_warnings(s: Session, dates: set[str]) -> list[str]:
    out = []
    for d in sorted(dates):
        day = dt.date.fromisoformat(d)
        rows = s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= (day - dt.timedelta(days=1)).isoformat(),
                                                   PlannedWorkout.date <= (day + dt.timedelta(days=1)).isoformat(),
                                                   PlannedWorkout.status != "skipped")).all()
        hard = {r.date for r in rows if _is_hard(r.data)}
        for a in sorted(hard):
            b = (dt.date.fromisoformat(a) + dt.timedelta(days=1)).isoformat()
            msg = _("Two hard days in a row ({a} and {b}): leave at least one easy day between quality sessions.", a=f"{a[8:]}/{a[5:7]}", b=f"{b[8:]}/{b[5:7]}")
            if b in hard and msg not in out:
                out.append(msg)
    return out


def push_to_garmin(s: Session, workout_ids: list[int]) -> list[dict]:
    res = []
    for wid in workout_ids:
        pw = s.get(PlannedWorkout, wid)
        if not pw or pw.data.get("sport") != "running":
            res.append({"id": wid, "ok": False, "error": _("not a running workout")})
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
    if s.exec(select(PlannedWorkout).where(PlannedWorkout.activity_id == act.id)).first():
        return
    pw = s.exec(select(PlannedWorkout).where(PlannedWorkout.date == act.date, PlannedWorkout.status.in_(["planned", "modified"]))).all()
    pw = [p for p in pw if p.data.get("sport") == "running"]
    if not pw and not s.exec(select(PlannedWorkout).where(PlannedWorkout.date == act.date, PlannedWorkout.status == "done")).first():
        # nothing planned that day: a run done a day or two late still counts for the missed session
        lo = (dt.date.fromisoformat(act.date) - dt.timedelta(days=2)).isoformat()
        pw = [p for p in s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= lo, PlannedWorkout.date < act.date,
                                                             PlannedWorkout.status.in_(["planned", "modified"]))
                                .order_by(PlannedWorkout.date.desc())).all()
              if p.data.get("sport") == "running" and not p.activity_id]
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
    m = s.exec(select(Meta).where(Meta.key == key)).first()
    return m.value if m else {}


def meta_set(s: Session, key: str, value: dict) -> None:
    m = s.exec(select(Meta).where(Meta.key == key)).first() or Meta(key=key)
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
    try:
        lt = training_load(s, 7)["today"]
    except Exception:  # noqa: BLE001 - readiness must work without load data
        lt = None
    return load.readiness(wellness_rows(s, 70), load_today=lt).to_dict()


def save_checkin(s: Session, feel: int | None, legs: int | None, sick: bool = False, note: str | None = None) -> dict:
    """Daily 2-question check-in (1 = fatal ... 5 = genial). Stored as a 'self' wellness row."""
    row = {"date": dt.date.today().isoformat(), "source": "self", "feel": feel, "legs": legs, "sick": bool(sick)}
    if note:
        row["note"] = note[:200]
    upsert_wellness(s, row)
    return readiness_view(s)


READINESS_SYSTEM = """You are the athlete's running coach (OpenRun). Write in {language}, warm tone, no greetings. From the
JSON with their state today (0-100 readiness score and its parts, planned workout and the app's proposal) explain in 2-3
sentences (60 words max.) why the proposal makes sense or why they can train as planned. Quote 1-2 concrete figures. No lists."""


def readiness_view(s: Session, explain: bool = False) -> dict:
    """Readiness + what it means for today's session: a proposal the athlete accepts or dismisses."""
    today = dt.date.today().isoformat()
    r = readiness_today(s)
    a = get_athlete(s)
    pws = [p for p in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == today)).all()
           if p.data.get("sport") == "running" and p.status in ("planned", "modified")]
    pw = pws[0] if pws else None
    proposal = None
    dismissed = meta_get(s, "readiness_dismissed").get("date") == today
    if pw and pw.status == "planned" and r["status"] in ("amber", "red") and not dismissed:
        new, msg = adapt.adjust_for_readiness(pw.data, r["status"], a.vdot or 40)
        if new is not pw.data:
            proposal = {"workout_id": pw.id, "from": pw.data.get("title"), "to": new.get("title"),
                        "to_km": new.get("distance_km"), "reason": msg}
    out = {"readiness": r, "workout": workout_dict(pw) if pw else None, "proposal": proposal,
           "checkin": next(({k: w.get(k) for k in ("feel", "legs", "sick")} for w in wellness_rows(s, 1)
                            if w["date"] == today and (w.get("feel") or w.get("legs") or w.get("sick"))), None)}
    cache = meta_get(s, "readiness_explain")
    key = f"{today}:{r.get('score')}:{r['status']}:{bool(proposal)}:{i18n.lang()}"
    out["explanation"] = cache.get("text") if cache.get("key") == key else None
    if explain and not out["explanation"]:
        import json

        from .ai import coach
        facts = {"readiness": {k: r.get(k) for k in ("status", "score", "components", "reasons")},
                 "entreno_hoy": pw.data.get("title") if pw else None, "propuesta": proposal}
        text = coach.complete(READINESS_SYSTEM.format(language=language_name()), json.dumps(facts, ensure_ascii=False, default=str), 300) if ai_allowed(s, "readiness") else None
        text = text or _readiness_fallback(r, proposal, pw)
        meta_set(s, "readiness_explain", {"key": key, "text": text})
        out["explanation"] = text
    return out


def _readiness_fallback(r: dict, proposal: dict | None, pw: PlannedWorkout | None) -> str:
    comps = sorted(r.get("components") or [], key=lambda c: c["score"])
    weak = ", ".join(f"{c['label'].lower()} {c['value']}" for c in comps[:2] if c["score"] < 60)
    if proposal:
        return _("Today you come in with {weak}. Better “{to}” than “{frm}”: you keep the stimulus without digging a deeper hole, and make up the quality another day.",
                 weak=weak or _("some fatigue"), to=proposal["to"], frm=proposal["from"])
    if pw and r["status"] == "green":
        return _("All in range (score {score}/100): go ahead with “{title}”.", score=r.get("score"), title=pw.data.get("title"))
    return _("Listen to your body: if your legs don't respond in the warm-up, keep it easy.")


def apply_readiness(s: Session, accept: bool) -> dict:
    if not accept:
        meta_set(s, "readiness_dismissed", {"date": dt.date.today().isoformat()})
        return readiness_view(s)
    adapt_today(s)
    return readiness_view(s)


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
        pw.note = _("Adjusted: 'not feeling 100%'")
        s.add(pw)
    s.commit()
    on_watch = [p.id for p in pws if p.garmin_workout_id and p.data.get("sport") == "running"]
    if on_watch:
        push_to_garmin(s, on_watch)
    return [workout_dict(p) for p in pws]


# ---------------------------------------------------------------- missed sessions & breaks

from .training import replan as RPL  # noqa: E402


def _rows(pws: list[PlannedWorkout]) -> list[dict]:
    return [{"id": p.id, "date": p.date, "status": p.status, "data": p.data, "activity_id": p.activity_id} for p in pws]


def replan_check(s: Session) -> dict:
    """Missed sessions of the last days and what to do with them (proposals, nothing is changed)."""
    today = dt.date.today()
    pws = s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= (today - dt.timedelta(days=6)).isoformat(),
                                              PlannedWorkout.date <= (today + dt.timedelta(days=7)).isoformat())).all()
    rows = _rows(pws)
    upcoming = [r for r in rows if r["date"] >= today.isoformat()]
    out = []
    for m in RPL.missed(rows, today):
        item = {"id": m["id"], "date": m["date"], "title": m["data"].get("title"), "key": RPL.is_key(m["data"]), "slot": None}
        if item["key"]:
            sl = RPL.slot_for(m, upcoming, today)
            if sl:
                rep = sl["replaces"]
                item["slot"] = {"date": sl["date"], "replaces_id": rep["id"] if rep else None,
                                "replaces_title": rep["data"].get("title") if rep else None}
        out.append(item)
    last_run = s.exec(select(Activity).where(Activity.sport == "running").order_by(Activity.date.desc())).first()
    gap = (today - dt.date.fromisoformat(last_run.date)).days if last_run else None
    return {"missed": out, "days_since_run": gap,
            "suggest_break": bool(gap and gap >= 4 and sum(1 for r in rows if r["date"] < today.isoformat() and r["status"] != "done"
                                                            and r["data"].get("sport") == "running") >= 2)}


def replan_apply(s: Session, workout_id: int, accept: bool) -> dict:
    """accept: move the missed key session to its proposed day (replacing the easy run there);
    otherwise mark it as not done."""
    pw = s.get(PlannedWorkout, workout_id)
    if not pw or pw.status not in ("planned", "modified"):
        raise ValueError(_("That workout is no longer pending"))
    item = next((m for m in replan_check(s)["missed"] if m["id"] == workout_id), None)
    touched = [pw]
    if accept and item and item["slot"]:
        sl = item["slot"]
        old = pw.date
        pw.date, pw.data = sl["date"], {**pw.data, "date": sl["date"]}
        pw.status, pw.note = "modified", _("Moved from {date}", date=f"{old[8:]}/{old[5:7]}")
        if sl["replaces_id"]:
            rep = s.get(PlannedWorkout, sl["replaces_id"])
            rep.status, rep.note = "skipped", _("Replaced by “{title}” (rescheduled)", title=pw.data.get("title"))
            s.add(rep)
            touched.append(rep)
        result = _("“{title}” moves to {date}.", title=pw.data.get("title"), date=f"{sl['date'][8:]}/{sl['date'][5:7]}")
    else:
        pw.status, pw.note = "skipped", _("Skipped")
        result = _("“{title}” marked as skipped.", title=pw.data.get("title"))
    s.add(pw)
    s.commit()
    _resync_garmin(s, touched)
    return {"message": result, **replan_check(s)}


def auto_skip_missed(s: Session) -> list[str]:
    """Daily: easy sessions missed before yesterday and key sessions with no slot left become 'skipped'
    (the plan stays honest and the weekly numbers right). Returns the titles of key sessions that
    still have a proposal, for the morning notification."""
    today = dt.date.today()
    chk = replan_check(s)
    pending = []
    for m in chk["missed"]:
        old = (today - dt.date.fromisoformat(m["date"])).days
        if (not m["key"] and old >= 2) or (m["key"] and not m["slot"] and old >= 2):
            pw = s.get(PlannedWorkout, m["id"])
            pw.status, pw.note = "skipped", _("Skipped")
            s.add(pw)
        elif m["key"] and m["slot"]:
            pending.append(m)
    s.commit()
    return pending


def _soften_range(s: Session, start: dt.date, days: int, mode: str, pct: int, note: str, vdot: float) -> list[PlannedWorkout]:
    """mode 'easy': every run becomes easy (quality -> easy, long -> shorter long); 'reduce': only volume -pct %."""
    paces = training_paces(vdot)
    out = []
    for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= start.isoformat(),
                                                  PlannedWorkout.date < (start + dt.timedelta(days=days)).isoformat(),
                                                  PlannedWorkout.status.in_(["planned", "modified"]))).all():
        d = pw.data
        if d.get("sport") != "running" or d.get("type") == "race":
            continue
        km = (d.get("distance_km") or 6) * (1 - pct / 100)
        if mode == "easy" or d.get("intensity") == "high":
            w = W.long_run(paces, km) if d.get("type") == "long" else W.easy_run(paces, max(3.0, km))
        elif d.get("type") == "long":
            w = W.long_run(paces, km)
        elif d.get("intensity") == "moderate":
            w = W.easy_with_strides(paces, max(3.0, km), 4)
        else:
            w = W.easy_run(paces, max(3.0, km))
        w.date, w.phase = pw.date, d.get("phase", "")
        pw.data, pw.status, pw.note = {**w.to_dict(), "_orig": d.get("_orig") or d}, "modified", note
        s.add(pw)
        out.append(pw)
    s.commit()
    return out


def report_break(s: Session, days_off: int, reason: str = "other") -> dict:
    """'I've been off N days': close the gap in the plan and ease back in (see training/replan.py)."""
    days_off = max(1, min(int(days_off), 120))
    today = dt.date.today()
    p = RPL.break_protocol(days_off, reason)
    label = {"illness": _("illness"), "injury": _("injury"), "travel": _("travel")}.get(reason) or _("break")
    for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= (today - dt.timedelta(days=days_off)).isoformat(),
                                                  PlannedWorkout.date < today.isoformat(),
                                                  PlannedWorkout.status.in_(["planned", "modified"]))).all():
        pw.status, pw.note = "skipped", f"{_('Skipped')} ({label})"
        s.add(pw)
    s.commit()
    a = get_athlete(s)
    vdot = a.vdot or 40.0
    if p["vdot_factor"] < 1 and a.vdot:
        vdot = round(a.vdot * p["vdot_factor"], 1)
        recalibrate_paces(s, vdot, _("return after {n} days of {label}", n=days_off, label=label))
    note = _("Return after {label} ({n} d)", label=label, n=days_off)
    touched = _soften_range(s, today, p["easy_days"], "easy", 30 if days_off > 7 else 20, note, vdot)
    if p["reduce_days"] > p["easy_days"]:
        touched += _soften_range(s, today + dt.timedelta(days=p["easy_days"]), p["reduce_days"] - p["easy_days"],
                                 "reduce", p["reduce_pct"], note, vdot)
    _resync_garmin(s, touched)
    log = meta_get(s, "breaks").get("items", [])
    meta_set(s, "breaks", {"items": (log + [{"date": today.isoformat(), "days": days_off, "reason": reason}])[-20:]})
    return {**p, "changed": len(touched), "vdot": vdot}


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
    d = r.model_dump(exclude={"course", "strategy"})
    d["has_course"] = bool(r.course and r.course.get("profile"))
    d["strategy_target_s"] = (r.strategy or {}).get("target_s")
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
    note = _("Adjusted for race: {name}", name=r.name)
    d = dt.date.fromisoformat(r.date)
    dist = r.distance_m or 10000

    for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == r.date)).all():
        if pw.data.get("sport") == "running" and pw.data.get("race_id") != r.id:
            pw.data = {**pw.data, "_orig": pw.data.get("_orig") or dict(pw.data)}
            pw.status, pw.note = "skipped", _("Replaced by {name}", name=r.name)
            s.add(pw)
            touched.append(pw)
            changes.append(f"{pw.date}: {pw.data.get('title')} → " + _("replaced by the race"))

    w = W.race(training_paces(vdot), "", dist, _zone_for(dist))
    w.title = f"🏁 {r.name}" + (" " + _("(C · at training pace)") if r.priority == "C" else "")
    if r.priority == "C":
        w.intensity = "moderate"
        w.description = _("Training race: controlled effort (threshold to 10K pace), without emptying the tank. It counts as a quality session.")
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
                    changes.append(f"{day}: " + _("pre-race shakeout"))
                elif x.data.get("intensity") in ("moderate", "high") or x.data.get("type") == "long":
                    _soften(x, vdot, note, "easy")
                    touched.append(x)
                    changes.append(f"{day}: " + _("quality → easy + strides"))
    rec_days = 1 if r.priority == "C" else min(7, max(2, round(dist / 3000)))
    for i in range(1, rec_days + 1):
        day = (d + dt.timedelta(days=i)).isoformat()
        for x in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == day, PlannedWorkout.status.in_(["planned", "modified"]))).all():
            if x.data.get("sport") == "running" and (i == 1 or x.data.get("intensity") in ("moderate", "high") or x.data.get("type") == "long"):
                _soften(x, vdot, note, "recovery" if i == 1 else "easy")
                touched.append(x)
                changes.append(f"{day}: " + (_("recovery run") if i == 1 else _("quality → easy")) + " " + _("(post-race recovery)"))
    s.commit()
    _resync_garmin(s, touched)
    suggestion = None
    if r.priority == "A" and (not plan or plan.summary.get("race_date") != r.date):
        suggestion = _("It's your goal race: generate a plan with this race date to periodise and taper towards it.")
    return {"changes": changes, "recovery_days": rec_days, "suggestion": suggestion}


def _restore_race_changes(s: Session, r: Race) -> None:
    notes = i18n.all_langs("Adjusted for race: {name}", name=r.name) | i18n.all_langs("Replaced by {name}", name=r.name)
    restored: list[PlannedWorkout] = []
    for pw in s.exec(select(PlannedWorkout)).all():
        if pw.data.get("race_id") == r.id:
            if pw.garmin_workout_id:
                try:
                    garmin.delete_workout(pw.garmin_workout_id)
                except Exception:  # noqa: BLE001
                    pass
            s.delete(pw)
        elif pw.note in notes and pw.data.get("_orig"):
            pw.data, pw.status, pw.note = pw.data["_orig"], "planned", None
            s.add(pw)
            restored.append(pw)
    s.commit()
    _resync_garmin(s, restored)


def list_races(s: Session) -> list[dict]:
    return [race_dict(r) for r in s.exec(select(Race).order_by(Race.date)).all()]


def add_race(s: Session, name: str, date: str, distance_m: float | None = None, priority: str = "B", **extra) -> dict:
    if priority not in ("A", "B", "C"):
        raise ValueError(_("priority A, B or C"))
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
        raise ValueError(_("race does not exist"))
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
    from .db import ActivityStream
    from .integrations.history_import import activities_from_upload

    keep_streams_from = (dt.date.today() - dt.timedelta(days=365)).isoformat()
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
            streams = a.pop("_streams", None)
            row = upsert_activity(s, a)
            if streams and a["date"] >= keep_streams_from:  # old history: summary only (keeps the DB small)
                s.add(ActivityStream(activity_id=row.id, data=streams))
                s.commit()
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
    from .tenancy import as_user, current_user_id

    uid = current_user_id()
    job_id = uuid.uuid4().hex[:12]
    job = IMPORT_JOBS[job_id] = {"id": job_id, "user_id": uid, "state": "running", "file": 0, "files": len(files), "done": 0, "total": 0,
                                 "stats": {}, "error": None}

    def progress(fi, nf, done, total, stats):
        job.update(file=fi + 1, files=nf, done=done, total=total, stats=dict(stats))

    def run():
        try:
            with as_user(uid), Session(engine) as s:
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


# ---------------------------------------------------------------- onboarding


def onboarding_state(s: Session) -> dict:
    """What a new user still has to set up; suggestions for the plan form from their history."""
    today = dt.date.today()
    runs = s.exec(select(Activity).where(Activity.sport == "running",
                                         Activity.date >= (today - dt.timedelta(days=42)).isoformat())).all()
    km4 = sum((r.data.get("distance_m") or 0) for r in runs if r.date >= (today - dt.timedelta(days=28)).isoformat()) / 1000
    a = get_athlete(s)
    done = bool(meta_get(s, "onboarding").get("done"))
    return {"done": done, "needed": not done and active_plan(s) is None,
            "activities": len(s.exec(select(Activity)).all()), "garmin": bool(garmin.status().get("connected")),
            "profile": bool(a.age and a.sex), "weekly_km": round(km4 / 4) if runs else None,
            "longest_km": round(max((r.data.get("distance_m") or 0) for r in runs) / 1000) if runs else None,
            "vdot": a.vdot}


def onboarding_done(s: Session) -> dict:
    meta_set(s, "onboarding", {"done": True, "at": dt.datetime.now().isoformat(timespec="seconds")})
    return onboarding_state(s)


# ---------------------------------------------------------------- AI usage limits

AI_DEFAULT_LIMIT = int(os.getenv("OPENRUN_AI_DAILY_LIMIT", "40"))


def ai_limit(uid: int) -> int | None:
    """Requests per day for this user; None = unlimited (admins unless an explicit limit is set)."""
    from .db import User
    with Session(engine) as s2:
        u = s2.get(User, uid)
    if not u:
        return 0
    if u.ai_daily_limit is not None:
        return u.ai_daily_limit
    return None if u.is_admin else AI_DEFAULT_LIMIT


def ai_usage(s: Session) -> dict:
    from .tenancy import current_user_id
    u = meta_get(s, "ai_usage")
    today = dt.date.today().isoformat()
    count = u.get("count", 0) if u.get("date") == today else 0
    return {"date": today, "count": count, "limit": ai_limit(current_user_id())}


def ai_allowed(s: Session, kind: str = "chat") -> bool:
    """Count one AI request for the current user; False when today's limit is reached (always in the demo)."""
    from . import demo
    from .tenancy import current_user_id

    if demo.is_demo(current_user_id()):
        return False
    u = ai_usage(s)
    if u["limit"] is not None and u["count"] >= u["limit"]:
        return False
    cur = meta_get(s, "ai_usage")
    by = cur.get("by_kind", {}) if cur.get("date") == u["date"] else {}
    by[kind] = by.get(kind, 0) + 1
    meta_set(s, "ai_usage", {"date": u["date"], "count": u["count"] + 1, "by_kind": by})
    return True


def ai_limit_message(s: Session) -> str:
    return _("You have reached the limit of {n} daily AI coach requests. It resets tomorrow; meanwhile the plan and the automatic adjustments keep working.", n=ai_usage(s)["limit"])


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
    "notify_morning": True,  # push: today's session after the morning routine
    "notify_analysis": True,  # push: post-run analysis when a run syncs
    "notify_weekly": True,   # push: Monday weekly review
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
    if act.sport != "running" or (laps_raw is None and not act.external_id.startswith("garmin:")):
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
                note = _("Paces +{pct}% for heat ({temp} °C, dew point {dew} °C at {hour}h). Keep the effort, not the pace.",
                         pct=f"{w['pct']:g}", temp=f"{w['temp']:.0f}", dew=f"{w['dew']:.0f}", hour=w["hour"])
                if w["too_hot"] and pw.data.get("intensity") in ("moderate", "high"):
                    note += " " + _("Extreme heat: better on a treadmill, first thing in the morning, or swap it for an easy run.")
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
    step("analysis", lambda: {"analysed": analyze_recent(s)})
    step("missed", lambda: {"pending": [m["title"] for m in auto_skip_missed(s)]})
    step("paces", lambda: (lambda r: {"applied": r["applied"], "pending": r["pending"]})(pace_insights(s)))
    if dt.date.today().weekday() == 0:
        step("weekly review", lambda: (lambda r: {"ai": r["ai"]})(weekly_review(s)))
    if st["heat_adjust"]:
        step("heat", lambda: apply_heat(s))
    if st["auto_adapt"]:
        step("readiness", lambda: adapt_today(s)["changes"])
    if connected and st["auto_push"]:
        step("watch", lambda: (lambda r: {"sent": sum(1 for x in r if x["ok"]), "errors": [x.get("error") for x in r if not x["ok"]]})(push_changed(s)))
    hist = meta_get(s, "daily_log").get("items", [])
    meta_set(s, "daily_log", {"items": (hist + [log])[-14:], "last_date": dt.date.today().isoformat()})
    try:
        morning_notifications(s, log, connected)
    except Exception:  # noqa: BLE001 - notifications are best effort
        pass
    return log


# ---------------------------------------------------------------- notifications


def notify(s: Session, kind: str | None, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Push to the current user's devices if they enabled this kind of notification."""
    from . import push
    from .tenancy import current_user_id

    if kind and not get_settings(s).get(f"notify_{kind}", True):
        return 0
    return push.send(current_user_id(), title, body, url, tag)


def today_message(s: Session) -> tuple[str, str] | None:
    today = dt.date.today().isoformat()
    ws = [w for w in list_workouts(s, today, today) if w["status"] in ("planned", "modified")]
    if not ws:
        return None
    run = next((w for w in ws if w.get("sport") == "running"), None)
    other = [w["title"] for w in ws if w is not run]
    if run:
        title = _("Today: {title}", title=run["title"])
        bits = [f"{run.get('distance_km')} km" if run.get("distance_km") else None]
        if run.get("_heat"):
            bits.append(_("paces +{pct}% for heat", pct=run["_heat"].get("pct")))
        if run["status"] == "modified":
            bits.append(_("adjusted to how you are today"))
        if other:
            bits.append(" + ".join(other))
        body = " · ".join(b for b in bits if b) or run.get("description", "")[:120]
    else:
        title, body = _("Today: {title}", title=other[0]), _("Strength session. Open it to see the exercises.")
    return title, body


def morning_notifications(s: Session, log: dict, connected: bool) -> None:
    sync = next((x for x in log["steps"] if x["step"] == "sync"), None)
    if sync and not sync["ok"] and any(k in (sync.get("error") or "").lower() for k in ("auth", "401", "login", "token", "not connected", "no conectado")):
        notify(s, None, _("Garmin disconnected"), _("Reconnect Garmin in Settings to sync and send workouts to the watch."), "/#ajustes", "garmin")
    msg = today_message(s)
    if msg:
        notify(s, "morning", msg[0], msg[1], "/#hoy", "today")
    lost = next((x for x in log["steps"] if x["step"] == "missed" and x["ok"]), None)
    pend = (lost or {}).get("result", {}).get("pending") or []
    if pend:
        notify(s, "morning", _("Shall we make up the session?"), _("I didn't see “{title}”. There's a slot to reschedule it this week: check Today.", title=pend[0]), "/#hoy", "replan")
    if dt.date.today().weekday() == 0:
        rev = meta_get(s, "weekly_reviews").get((_monday(dt.date.today()) - dt.timedelta(days=7)).isoformat())
        if rev:
            notify(s, "weekly", _("Your weekly summary"), rev["comment"][:200], "/#hoy", "weekly")


VERDICT_TEXT = {"on_target": N_("on target ✅"), "too_easy": N_("easier than planned"), "too_hard": N_("harder than planned")}


def intraday_sync(s: Session) -> dict:
    """Light sync during the day: new runs get analysed and notified right away."""
    if not garmin.status().get("connected"):
        return {"skipped": "garmin"}
    before = {a.id for a in s.exec(select(Activity)).all()}
    end = dt.date.today()
    for a in garmin.fetch_activities(end - dt.timedelta(days=1), end):
        upsert_activity(s, a)
    new = [a for a in s.exec(select(Activity).where(Activity.date >= (end - dt.timedelta(days=1)).isoformat())).all()
           if a.id not in before and a.sport == "running"]
    for act in new:
        try:
            res = analyze_activity(s, act)
        except Exception:  # noqa: BLE001
            res = None
        km = round((act.data.get("distance_m") or 0) / 1000, 1)
        title = f"{act.data.get('name') or _('Run')} · {km} km"
        if res and res.get("planned_title"):
            body = f"{res['planned_title']}: {_(VERDICT_TEXT.get(res.get('verdict'), 'analysed'))}."
            if res.get("notes"):
                body += " " + res["notes"][0]
        else:
            body = _("Synced. Check the map and your splits.")
        notify(s, "analysis", title, body, "/#progreso", f"act-{act.id}")
    return {"new": len(new)}


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


def delete_user(uid: int) -> None:
    """Remove an account and every row it owns (admin action)."""
    from sqlalchemy import delete

    from .db import PushSubscription, User, engine
    from .tenancy import TENANT_MODELS

    with Session(engine) as s:
        for m in TENANT_MODELS:
            s.exec(delete(m).where(m.user_id == uid))
        s.exec(delete(PushSubscription).where(PushSubscription.user_id == uid))
        u = s.get(User, uid)
        if u:
            s.delete(u)
        s.commit()
    garmin.forget(uid)
    i18n.forget_user(uid)


# ---------------------------------------------------------------- race-day strategy

from .training import race_plan as RP  # noqa: E402

MODES = {"conservative": 1.02, "realistic": 1.0, "ambitious": 0.985}


def _race_course(r: Race) -> dict:
    if r.course and r.course.get("profile"):
        return {**r.course, "builtin": False}
    b = RP.builtin_for(r.name)
    if b and (not r.distance_m or abs(r.distance_m - b["distance_m"]) < 1500):
        return {**b, "builtin": True}
    dist = r.distance_m or 10000
    return {"name": _("Flat course (upload the GPX for the real profile)"), "profile": RP.flat_profile(dist), "flat": True, "builtin": False}


def race_weather(lat: float, lon: float, date: str, hour: int) -> dict | None:
    """Race-day forecast (Open-Meteo, up to 16 days ahead)."""
    import httpx

    days = (dt.date.fromisoformat(date) - dt.date.today()).days
    if days < 0 or days > 15:
        return None
    r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
        "latitude": round(lat, 3), "longitude": round(lon, 3), "timezone": "auto", "forecast_days": 16,
        "hourly": "temperature_2m,dew_point_2m,precipitation_probability,wind_speed_10m"})
    r.raise_for_status()
    h = r.json()["hourly"]
    key = f"{date}T{hour:02d}:00"
    if key not in h["time"]:
        return None
    i = h["time"].index(key)
    w = {"temp": h["temperature_2m"][i], "dew": h["dew_point_2m"][i], "rain_pct": h["precipitation_probability"][i],
         "wind_kmh": h["wind_speed_10m"][i], "hour": hour, "days_ahead": days}
    if w["temp"] is not None and w["dew"] is not None:
        w["slowdown_pct"], w["hadley_f"] = HEAT.slowdown_pct(w["temp"], w["dew"])
    return w


def race_strategy(s: Session, race_id: int, mode: str | None = None, target_s: float | None = None,
                  start_time: str | None = None) -> dict:
    r = s.get(Race, race_id)
    if not r:
        raise ValueError(_("race does not exist"))
    saved = r.strategy or {}
    mode = mode or saved.get("mode") or "realistic"
    course = _race_course(r)
    profile = course["profile"]
    distance = profile[-1][0]
    cf = RP.course_factor(profile)
    a = get_athlete(s)
    from .training.vdot import predict_race_time
    flat = predict_race_time(a.vdot, distance) if a.vdot else None
    predicted = flat * cf if flat else None
    start_time = start_time or saved.get("start_time") or course.get("start_time") or "10:00"
    loc = course.get("start") or (_location(s) and list(_location(s)))
    weather = None
    if loc:
        try:
            weather = race_weather(loc[0], loc[1], r.date, int(start_time[:2]))
        except Exception:  # noqa: BLE001 - forecast is optional
            weather = None
    heat_pct = (weather or {}).get("slowdown_pct", 0.0) or 0.0
    custom = target_s or (saved.get("target_s") if mode == "custom" else None)
    if custom:
        mode, base = "custom", float(custom)
    elif predicted:
        base = predicted * MODES.get(mode, 1.0)
    elif r.goal_time_s:
        mode, base = "goal", r.goal_time_s
    else:
        raise ValueError(_("I need your VDOT (Settings › Profile) or a goal time to compute the strategy"))
    target = base * (1 + heat_pct / 100)
    plan = RP.pace_plan(profile, target, course.get("notes"))
    gain, loss = RP.gain_loss(profile)
    step = max(1, len(profile) // 200)
    return {
        "race": race_dict(r), "mode": mode, "start_time": start_time,
        "course": {"name": course.get("name"), "approx": course.get("approx", False), "flat": course.get("flat", False),
                   "builtin": course.get("builtin", False), "distance_m": distance, "gain_m": gain, "loss_m": loss,
                   "profile": profile[::step] + ([profile[-1]] if (len(profile) - 1) % step else []),
                   "coords": course.get("coords"), "factor": round(cf, 4)},
        "prediction": {"vdot": a.vdot, "flat_s": round(flat) if flat else None, "course_s": round(predicted) if predicted else None,
                       "modes": {k: round(predicted * v * (1 + heat_pct / 100)) for k, v in MODES.items()} if predicted else {},
                       "goal_s": r.goal_time_s},
        "weather": weather, "heat_pct": heat_pct, "target_s": round(target), **plan,
        "fuel": RP.fuelling(target, a.weight_kg, distance),
        "tips": RP.strategy_tips(target, cf, heat_pct),
    }


def save_race_strategy(s: Session, race_id: int, mode: str | None, target_s: float | None, start_time: str | None) -> dict:
    r = s.get(Race, race_id)
    if not r:
        raise ValueError(_("race does not exist"))
    cur = dict(r.strategy or {})
    if mode:
        cur["mode"] = mode
    if target_s:
        cur["target_s"], cur["mode"] = float(target_s), "custom"
    if start_time:
        cur["start_time"] = start_time
    r.strategy = cur
    s.add(r)
    s.commit()
    return race_strategy(s, race_id)


def set_race_course(s: Session, race_id: int, filename: str, content: bytes) -> dict:
    r = s.get(Race, race_id)
    if not r:
        raise ValueError(_("race does not exist"))
    pts = RP.fill_elevation(RP.parse_track(filename, content))
    profile = RP.profile_from_track(pts)
    builtin = RP.builtin_for(r.name)
    r.course = {"name": filename, "profile": profile, "coords": RP.course_coords(pts), "start": [pts[0][0], pts[0][1]],
                "notes": builtin["notes"] if builtin else None,
                "start_time": builtin.get("start_time") if builtin else None}
    if not r.distance_m:
        r.distance_m = round(profile[-1][0])
    s.add(r)
    s.commit()
    return race_strategy(s, race_id)


def clear_race_course(s: Session, race_id: int) -> dict:
    r = s.get(Race, race_id)
    if r:
        r.course = None
        s.add(r)
        s.commit()
    return race_strategy(s, race_id)


def push_race_strategy(s: Session, race_id: int) -> dict:
    """Race-day workout with one step per km at the strategy's target pace; on the watch if connected."""
    st = race_strategy(s, race_id)
    r = s.get(Race, race_id)
    existing = next((pw for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date == r.date)).all()
                     if pw.data.get("race_id") == r.id or pw.data.get("type") == "race"), None)
    from .training.vdot import fmt_pace
    desc = _("{name} strategy: goal {goal} ({pace}/km average, {gain} m D+). Pace per km adjusted for elevation: run the climbs by effort.",
             name=r.name, goal=fmt_time(st["target_s"]), pace=fmt_pace(st["avg_pace_s"]), gain=st["course"]["gain_m"])
    w = save_custom_workout(s, r.date, f"🏁 {r.name}"[:50], "race", RP.watch_steps(st["kms"]), desc, "high",
                            existing.id if existing else None)
    pw = s.get(PlannedWorkout, w["id"])
    pw.data = {**pw.data, "race_id": r.id}
    s.add(pw)
    s.commit()
    pushed = None
    if garmin.status().get("connected"):
        pushed = push_to_garmin(s, [pw.id])[0]
    return {"workout": workout_dict(pw), "garmin": pushed}


# ---------------------------------------------------------------- activity detail (map, charts, km splits)


def km_splits(st: dict) -> list[dict]:
    d, tt = st.get("d") or [], st.get("t") or []
    if len(d) < 2 or len(tt) != len(d):
        return []
    out, start_i, next_km = [], 0, 1000.0

    def avg(key: str, a: int, b: int):
        vals = [v for v in (st.get(key) or [])[a:b + 1] if v]
        return round(sum(vals) / len(vals)) if vals else None

    for i in range(1, len(d)):
        if d[i] is None or tt[i] is None:
            continue
        last = i == len(d) - 1
        if d[i] >= next_km or last:
            dist = d[i] - (d[start_i] or 0)
            if dist < 200 and last and out:
                break
            secs = tt[i] - (tt[start_i] or 0)
            ele = [e for e in (st.get("ele") or [])[start_i:i + 1] if e is not None]
            gain = sum(max(0.0, b - a) for a, b in zip(ele, ele[1:]))
            out.append({"km": len(out) + 1, "distance_m": round(dist), "time_s": round(secs),
                        "pace_s": round(secs / dist * 1000, 1) if dist > 0 else None,
                        "hr": avg("hr", start_i, i), "cad": avg("cad", start_i, i), "gain_m": round(gain)})
            start_i, next_km = i, next_km + 1000.0
    return out


def activity_detail(s: Session, activity_id: int, refresh: bool = False) -> dict:
    from .db import ActivityStream

    act = s.get(Activity, activity_id)
    if not act:
        raise ValueError(_("activity does not exist"))
    row = s.get(ActivityStream, activity_id)
    if (row is None or refresh) and act.external_id.startswith("garmin:"):
        streams = garmin.fetch_streams(act.external_id)
        row = row or ActivityStream(activity_id=activity_id)
        row.data = streams
        s.add(row)
        s.commit()
    st = row.data if row else {}
    lat, lon = st.get("lat") or [], st.get("lon") or []
    coords = [[a, b] for a, b in zip(lat, lon) if a is not None and b is not None]

    def mean(key):
        vals = [v for v in st.get(key) or [] if v]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {"activity": {**{k: v for k, v in act.data.items() if k not in ("analysis",)}, "id": act.id, "date": act.date},
            "has_streams": bool(st), "streams": {k: v for k, v in st.items() if k not in ("lat", "lon")},
            "coords": coords, "splits": km_splits(st),
            "dynamics": {"cadence": mean("cad"), "stride_cm": mean("stride"), "gct_ms": mean("gct"),
                         "vertical_osc_cm": mean("vo"), "power_w": mean("power")}}


# ---------------------------------------------------------------- weekly review

REVIEW_SYSTEM = """You are the athlete's running coach (OpenRun). Write in {language}, warm and direct, no greetings or
sign-offs. From the JSON data of their week (keys are in Spanish) write 3 short paragraphs (90 words max. in total):
1) how the week went (completion, how the key sessions felt, load); 2) what it means (fitness, fatigue, risk);
3) a concrete focus for next week. Don't make up data that isn't in the JSON. No lists or headings."""


def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def weekly_facts(s: Session, week_start: dt.date) -> dict:
    end = week_start + dt.timedelta(days=6)
    a0, a1 = week_start.isoformat(), end.isoformat()
    planned = [workout_dict(pw) for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= a0, PlannedWorkout.date <= a1)).all()]
    runs_p = [w for w in planned if w.get("sport") == "running"]
    acts = s.exec(select(Activity).where(Activity.date >= a0, Activity.date <= a1)).all()
    runs = [x for x in acts if x.sport == "running"]
    km = sum((x.data.get("distance_m") or 0) for x in runs) / 1000
    km_plan = sum(w.get("distance_km") or 0 for w in runs_p if w["status"] != "skipped")
    done = [w for w in planned if w["status"] == "done"]
    skipped = [w for w in planned if w["status"] == "skipped"]
    key = []
    for x in runs:
        an = x.data.get("analysis") or {}
        if an.get("planned_title") or an.get("verdict"):
            key.append({"fecha": x.date, "sesion": an.get("planned_title") or x.data.get("name"), "veredicto": an.get("verdict"),
                        "en_rango_pct": an.get("on_target_pct"), "notas": (an.get("notes") or [])[:2]})
    tl = training_load(s, 60)["series"]
    by_date = {r["date"]: r for r in tl}
    l_end = by_date.get(a1) or (tl[-1] if tl else None)
    l_start = by_date.get((week_start - dt.timedelta(days=1)).isoformat())
    nxt0, nxt1 = (end + dt.timedelta(days=1)).isoformat(), (end + dt.timedelta(days=7)).isoformat()
    upcoming = [workout_dict(pw) for pw in s.exec(select(PlannedWorkout).where(PlannedWorkout.date >= nxt0, PlannedWorkout.date <= nxt1)).all()]
    up_runs = [w for w in upcoming if w.get("sport") == "running"]
    hard = [f"{w['date'][8:]}/{w['date'][5:7]} {w['title']}" for w in up_runs if w.get("intensity") in ("high", "moderate") or w.get("type") in ("long", "race")]
    races = [race_dict(r) for r in s.exec(select(Race).where(Race.date >= nxt0).order_by(Race.date)).all()][:2]
    outings = []
    from .training.vdot import fmt_pace
    for x in sorted(runs, key=lambda r: r.date):
        dist, dur = x.data.get("distance_m") or 0, x.data.get("duration_s") or 0
        outings.append({"fecha": x.date, "km": round(dist / 1000, 1), "ritmo": fmt_pace(dur / dist * 1000) if dist > 500 else None,
                        "fc": x.data.get("avg_hr"), "te": x.data.get("training_effect"), "nombre": (x.data.get("name") or "")[:40]})
    low = sum(w.get("low_intensity_min") or 0 for w in runs_p)
    tot = sum(w.get("duration_min") or 0 for w in runs_p)
    return {
        "semana": {"desde": a0, "hasta": a1},
        "km": round(km, 1), "km_plan": round(km_plan, 1), "carreras": len(runs),
        "sesiones_plan": len(planned), "hechas": len(done), "saltadas": len(skipped),
        "cumplimiento_pct": round(100 * len(done) / len(planned)) if planned else None,
        "baja_intensidad_plan_pct": round(100 * low / tot) if tot else None,
        "salidas": outings[:10],
        "sesiones_clave": key[:4],
        "carga": {"ctl": l_end and l_end["ctl"], "ctl_cambio": l_end and l_start and round(l_end["ctl"] - l_start["ctl"], 1),
                  "tsb": l_end and l_end["tsb"], "acwr": l_end and l_end["acwr"]},
        "vdot": get_athlete(s).vdot,
        "readiness": readiness_today(s).get("status"),
        "proxima_semana": {"km": round(sum(w.get("distance_km") or 0 for w in up_runs), 1), "clave": hard[:4]},
        "proximas_carreras": [{"nombre": r["name"], "fecha": r["date"], "dias": r["days_to_go"]} for r in races],
    }


def _fallback_comment(f: dict) -> str:
    parts = []
    if f["cumplimiento_pct"] is not None:
        parts.append(_("You completed {done} of {total} sessions ({pct}%) and ran {km} of {km_plan} planned km.",
                       done=f["hechas"], total=f["sesiones_plan"], pct=f["cumplimiento_pct"], km=f["km"], km_plan=f["km_plan"]))
    else:
        parts.append(_("You ran {km} km in {n} runs.", km=f["km"], n=f["carreras"]))
    c = f["carga"]
    if c.get("acwr"):
        parts.append(_("Load is rising fast (ACWR > 1.3): prioritise sleep and don't add extras.") if c["acwr"] > 1.3
                     else _("Stable load.") if c["acwr"] >= 0.8 else _("Easy week: a good time to absorb the training."))
    if f["proxima_semana"]["clave"]:
        parts.append(_("Next week, what matters: ") + ", ".join(f["proxima_semana"]["clave"]) + ".")
    return " ".join(parts)


def weekly_review(s: Session, week_start: str | None = None, regenerate: bool = False, ai: bool = True) -> dict:
    """Review of a Monday-Sunday week (default: the last finished one). Cached in Meta."""
    ws = dt.date.fromisoformat(week_start) if week_start else _monday(dt.date.today()) - dt.timedelta(days=7)
    ws = _monday(ws)
    store = meta_get(s, "weekly_reviews")
    key = ws.isoformat()
    if key in store and not regenerate and store[key].get("lang", "es") == i18n.lang():  # pre-i18n reviews were Spanish
        return store[key]
    facts = weekly_facts(s, ws)
    text = None
    if ai:
        from .ai import coach
        text = None if not ai_allowed(s, "weekly") else coach.complete(REVIEW_SYSTEM.format(language=language_name()), json.dumps(facts, ensure_ascii=False, default=str))
    review = {"week_start": key, "facts": facts, "comment": text or _fallback_comment(facts), "ai": bool(text), "lang": i18n.lang(),
              "created_at": dt.datetime.now().isoformat(timespec="seconds")}
    store[key] = review
    for old in sorted(store)[:-12]:  # keep ~3 months
        store.pop(old)
    meta_set(s, "weekly_reviews", store)
    return review


def list_reviews(s: Session) -> list[dict]:
    store = meta_get(s, "weekly_reviews")
    return [store[k] for k in sorted(store, reverse=True)]
