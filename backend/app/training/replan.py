"""Re-adjusting the plan after missed sessions and after a break (illness, injury, travel).

Missed sessions: easy runs are simply dropped (making them up only piles fatigue on the next
days). A missed key session (quality or long run) is moved to the next suitable day in the next
few days, replacing an easy run, never next to another hard day (hard/easy principle, Bowerman;
Seiler 2010 polarised distribution). If there is no such day it is dropped: one missed session
costs nothing measurable, cramming two hard days does (overreaching risk).

Breaks: short layoffs barely detrain (< ~1 week: VO2max practically intact; 2-4 weeks: -4-7 %;
> 8 weeks: much larger losses — Mujika & Padilla 2000; Coyle 1984). Return-to-run follows
Daniels' guidance (Daniels' Running Formula, "Breaks"): <= 5 days no VDOT change; 6-28 days up to
~-7 %; longer, more and a rebuilt plan. After illness, easy days ~= days ill; with fever or chest
symptoms no training until 24-48 h symptom-free ("neck check", Eichner 1993; Nieman).
"""

from __future__ import annotations

import datetime as dt

from ..i18n import _


def is_key(data: dict) -> bool:
    return data.get("sport") == "running" and data.get("type") != "race" and (
        data.get("intensity") in ("high", "moderate") or data.get("type") == "long")


def is_hard(data: dict) -> bool:
    return data.get("sport") == "running" and (data.get("intensity") in ("high", "moderate") or data.get("type") in ("long", "race"))


def missed(workouts: list[dict], today: dt.date, lookback: int = 4) -> list[dict]:
    """Running sessions in the last `lookback` days still planned and without an activity."""
    lo = (today - dt.timedelta(days=lookback)).isoformat()
    return [w for w in workouts if lo <= w["date"] < today.isoformat() and w["status"] in ("planned", "modified")
            and w["data"].get("sport") == "running" and not w.get("activity_id")]


def slot_for(m: dict, upcoming: list[dict], today: dt.date, horizon: int = 4) -> dict | None:
    """Where a missed key session fits: the first day in the next `horizon` days whose running is
    easy (or empty), without a hard day before or after. Long runs only move up to 3 days."""
    by_day: dict[str, list[dict]] = {}
    for w in upcoming:
        if w["status"] in ("planned", "modified"):
            by_day.setdefault(w["date"], []).append(w)
    span = 3 if m["data"].get("type") == "long" else horizon
    missed_day = dt.date.fromisoformat(m["date"])
    for i in range(span):
        d = today + dt.timedelta(days=i)
        if (d - missed_day).days > 6:  # do not carry a session into a different training block
            break
        runs = [w for w in by_day.get(d.isoformat(), []) if w["data"].get("sport") == "running"]
        if any(is_hard(w["data"]) for w in runs):
            continue
        near = [w for k in (-1, 1) for w in by_day.get((d + dt.timedelta(days=k)).isoformat(), [])]
        if any(is_hard(w["data"]) for w in near):
            continue
        return {"date": d.isoformat(), "replaces": runs[0] if runs else None}
    return None


def vdot_factor(days_off: int) -> float:
    """Fraction of VDOT kept after `days_off` days without running (Daniels' break guidance)."""
    if days_off <= 5:
        return 1.0
    if days_off <= 28:
        return round(1 - 0.07 * (days_off - 5) / 23, 3)
    if days_off <= 56:
        return round(0.93 - 0.07 * (days_off - 28) / 28, 3)
    return 0.85


def break_protocol(days_off: int, reason: str = "other") -> dict:
    """How to come back: easy-only days, then reduced volume, and whether to rebuild the plan."""
    ill, injury = reason == "illness", reason == "injury"
    if days_off <= 2:
        easy, reduce, pct = 1, 0, 0
    elif days_off <= 7:
        easy, reduce, pct = (days_off if ill else max(2, days_off // 2)), 7, 20
    elif days_off <= 14:
        easy, reduce, pct = 5, 14, 30
    else:
        easy, reduce, pct = 7, 14, 30
    if injury:
        easy, pct = easy + 2, pct + 10
    notes = []
    if ill:
        notes.append(_("If you had a fever or chest symptoms, wait 24-48 h without symptoms before running again."))
    if injury:
        notes.append(_("No pain while running or the next day; if it comes back, stop and see a physio."))
    if days_off > 5:
        notes.append(_("Paces adjusted to your current fitness (≈ −{pct}% VDOT after {n} days).", pct=round((1 - vdot_factor(days_off)) * 100), n=days_off))
    return {"days_off": days_off, "easy_days": easy, "reduce_days": reduce, "reduce_pct": pct,
            "vdot_factor": vdot_factor(days_off), "rebuild": days_off > 28, "notes": notes}
