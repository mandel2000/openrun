"""Post-workout analysis: real laps vs the planned workout, and automatic pace insights.

Garmin records one lap per executed workout step (`wktStepIndex` = stepOrder - 1 of the uploaded
workout, repeats share the child's index), so each lap maps back to the planned step and its
pace range.

Session verdict (quality sessions only, i.e. steps at marathon pace or faster):
- too_easy: work reps on average >= 2 % faster than the fast end of the range, without HR above
  the zone ceiling (threshold work <= LTHR + 2 %). Fitness has likely improved.
- too_hard: >= half of the work reps >= 3 % slower than the slow end, or threshold work with HR
  > LTHR + 5 % while on pace. Paces are too ambitious or fatigue is high.
- on_target otherwise.
Pace insight (like Runna's): 2 of the last 3 analysed quality sessions (21 days) in the same
direction -> VDOT ±0.5, at most once every 7 days and never within 10 days of a goal race.
This is conservative on purpose: one great day (or a hot one) should not move all the paces.
"""

from __future__ import annotations

import datetime as dt

from ..i18n import _

QUALITY_ZONES = {"marathon", "half", "threshold", "ten_k", "five_k", "interval", "repetition"}
HR_CHECKED = {"marathon", "half", "threshold"}  # HR lags too much in short I/R reps to judge
EASY_ZONES = {"recovery", "easy", "long"}


def step_index_map(steps: list[dict]) -> dict[int, dict]:
    """stepOrder-1 -> step, in the same pre-order numbering used when uploading to Garmin."""
    out: dict[int, dict] = {}
    counter = [0]

    def walk(items: list[dict]) -> None:
        for st in items:
            idx = counter[0]
            counter[0] += 1
            if st.get("kind") == "repeat":
                walk(st.get("steps") or [])
            else:
                out[idx] = st

    walk(steps)
    return out


def normalize_laps(raw: list[dict]) -> list[dict]:
    laps = []
    for lp in raw:
        dist, dur = lp.get("distance") or 0, lp.get("movingDuration") or lp.get("duration") or 0
        laps.append({
            "i": lp.get("lapIndex"), "type": (lp.get("intensityType") or "").upper(), "step": lp.get("wktStepIndex"),
            "distance_m": round(dist, 1), "duration_s": round(dur, 1),
            "pace": round(dur / (dist / 1000), 1) if dist > 50 and dur else None,
            "avg_hr": lp.get("averageHR"), "max_hr": lp.get("maxHR"), "compliance": lp.get("directWorkoutComplianceScore"),
        })
    return laps


def analyze(laps: list[dict], planned: dict | None, lthr: int | None = None) -> dict:
    """laps: normalize_laps output. planned: workout dict (steps with zone/pace_slow/pace_fast)."""
    steps = step_index_map(planned.get("steps") or []) if planned else {}
    rows, work = [], []
    for lp in laps:
        st = steps.get(lp["step"]) if lp["step"] is not None else None
        row = {**lp, "zone": st.get("zone") if st else None, "kind": st.get("kind") if st else None,
               "target": [st.get("pace_slow"), st.get("pace_fast")] if st and st.get("pace_slow") else None, "status": None, "dev_pct": None}
        if row["target"] and lp["pace"] and lp["distance_m"] >= 150:
            slow, fast = row["target"]
            if lp["pace"] < fast:
                row["dev_pct"] = round((fast - lp["pace"]) / fast * 100, 1)  # positive = faster than range
                row["status"] = "fast" if row["dev_pct"] > 2 else "ok"
            elif lp["pace"] > slow:
                row["dev_pct"] = round(-(lp["pace"] - slow) / slow * 100, 1)
                row["status"] = "slow" if row["dev_pct"] < -2 else "ok"
            else:
                row["dev_pct"], row["status"] = 0.0, "ok"
            if st.get("kind") == "run" and row["zone"] in QUALITY_ZONES:
                work.append(row)
        rows.append(row)

    out: dict = {"laps": rows, "n_work": len(work), "verdict": None, "notes": []}
    if planned:
        easy_rows = [r for r in rows if r["zone"] in EASY_ZONES and r["kind"] == "run" and r["dev_pct"] is not None]
        if easy_rows and sum(r["dev_pct"] for r in easy_rows) / len(easy_rows) > 5:
            out["notes"].append(_("The easy parts were too fast: easy running should be conversational (80/20)."))
    if not work:
        return out
    on = sum(1 for r in work if r["status"] == "ok")
    avg_dev = sum(r["dev_pct"] for r in work) / len(work)
    slow_n = sum(1 for r in work if r["dev_pct"] < -3)
    hr_work = [r for r in work if r["zone"] in HR_CHECKED and r["avg_hr"]]
    hr_avg = sum(r["avg_hr"] for r in hr_work) / len(hr_work) if hr_work else None
    out.update(on_target_pct=round(on / len(work) * 100), avg_dev_pct=round(avg_dev, 1), work_hr=round(hr_avg) if hr_avg else None)

    if slow_n * 2 >= len(work) or (lthr and hr_avg and hr_avg > lthr * 1.05 and avg_dev >= -2):
        out["verdict"] = "too_hard"
        out["notes"].append(_("The reps were harder than planned (slower pace or high HR). If it happens again, paces will come down."))
    elif avg_dev >= 2 and not (lthr and hr_avg and hr_avg > lthr * 1.02):
        out["verdict"] = "too_easy"
        out["notes"].append(_("Reps faster than target without a spike in HR: your fitness may have improved."))
    else:
        out["verdict"] = "on_target"
        out["notes"].append(_("Session within the target paces."))
    return out


def pace_insight(sessions: list[dict], today: dt.date, last_change: str | None, goal_race: str | None,
                 vdot: float) -> dict | None:
    """sessions: [{date, verdict}] of analysed quality sessions. Returns a proposed change or None."""
    recent = sorted((x for x in sessions if x.get("verdict") in ("too_easy", "too_hard", "on_target")
                     and (today - dt.date.fromisoformat(x["date"])).days <= 21), key=lambda x: x["date"])[-3:]
    if len(recent) < 2:
        return None
    if last_change and (today - dt.date.fromisoformat(last_change)).days < 7:
        return None
    if goal_race and 0 <= (dt.date.fromisoformat(goal_race) - today).days <= 10:
        return None
    easy = sum(1 for x in recent if x["verdict"] == "too_easy")
    hard = sum(1 for x in recent if x["verdict"] == "too_hard")
    if easy >= 2 and hard == 0:
        return {"from": vdot, "to": round(vdot + 0.5, 1), "reason": _("{n} of your last {total} quality sessions were faster than target without a high HR", n=easy, total=len(recent))}
    if hard >= 2:
        return {"from": vdot, "to": round(vdot - 0.5, 1), "reason": _("{n} of your last {total} quality sessions were harder than planned", n=hard, total=len(recent))}
    return None
