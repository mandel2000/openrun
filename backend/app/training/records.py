"""Personal records (best efforts) and race-time predictions.

Best efforts come from Garmin's per-activity fastest splits (fastestSplit_<metres>), which are
the fastest contiguous segment of that length inside any run. When a split is missing (e.g. a
9.95 km "10K" or older activities), a whole activity within -0.5 %/+5 % of the distance counts,
pace-scaled to the exact distance, and is flagged as approximate.

Prediction models:
- VDOT (Daniels & Gilbert): best VDOT among efforts >= 1 mile in the last 90 days.
- Riegel (1981): T2 = T1 * (D2/D1)^1.06 from the effort closest in distance (log scale).
- Garmin race predictor (from the watch), when synced.
- Heart-rate VDOT estimate (Swain %HRR), orientative.
Consensus = median of the available models.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics

from ..i18n import N_, _
from .vdot import fmt_time, predict_race_time, vdot_from_race

PR_DISTANCES = {"1k": 1000.0, "mile": 1609.344, "5k": 5000.0, "10k": 10000.0, "half": 21097.5, "marathon": 42195.0}
PREDICT_DISTANCES = ("5k", "10k", "half", "marathon")
LABEL = {"1k": "1K", "mile": N_("Mile"), "5k": "5K", "10k": "10K", "half": N_("Half marathon"), "marathon": N_("Marathon")}
WINDOWS = {"all": None, "1y": 365, "6m": 182, "1m": 30}
RIEGEL_EXP = 1.06


def _split_key(metres: float) -> str | None:
    for k, d in PR_DISTANCES.items():
        if abs(d - metres) <= 2:
            return k
    return None


def best_efforts(act: dict) -> dict[str, dict]:
    """{distance_key: {"time_s", "approx"}} for one running activity."""
    out: dict[str, dict] = {}
    for m, t in (act.get("best_efforts") or {}).items():
        k = _split_key(float(m))
        if k and t:
            out[k] = {"time_s": float(t), "approx": bool(act.get("gps_only"))}  # GPS-only tracks are less precise
    dist, dur = act.get("distance_m") or 0, act.get("duration_s") or 0
    if dist and dur:
        for k, d in PR_DISTANCES.items():
            if k not in out and d * 0.995 <= dist <= d * 1.05:
                out[k] = {"time_s": dur * d / dist, "approx": True}
    return out


def records(activities: list[dict], today: dt.date | None = None) -> dict:
    """Best effort per distance for each window. Activities need date, id, name, sport."""
    today = today or dt.date.today()
    out: dict[str, dict] = {w: {} for w in WINDOWS}
    for a in activities:
        if a.get("sport") != "running":
            continue
        age = (today - dt.date.fromisoformat(a["date"])).days
        for k, e in best_efforts(a).items():
            item = {"time_s": round(e["time_s"], 1), "time": fmt_time(e["time_s"]), "approx": e["approx"],
                    "pace": fmt_time(e["time_s"] / (PR_DISTANCES[k] / 1000)), "date": a["date"],
                    "activity_id": a.get("id"), "name": a.get("name"), "external_id": a.get("external_id")}
            for w, days in WINDOWS.items():
                if days is not None and age > days:
                    continue
                cur = out[w].get(k)
                if cur is None or item["time_s"] < cur["time_s"]:
                    out[w][k] = item
    return out


def _effort_vdots(activities: list[dict], since: dt.date) -> list[dict]:
    res = []
    for a in activities:
        if a.get("sport") != "running" or dt.date.fromisoformat(a["date"]) < since:
            continue
        for k, e in best_efforts(a).items():
            if PR_DISTANCES[k] >= 1600:  # VDOT tables start at ~1500 m
                res.append({"key": k, "time_s": e["time_s"], "date": a["date"], "approx": e["approx"],
                            "vdot": vdot_from_race(PR_DISTANCES[k], e["time_s"])})
    return res


def vdot_trend(activities: list[dict], today: dt.date | None = None, months: int = 12) -> list[dict]:
    """Best effort VDOT per calendar month (only months with efforts)."""
    today = today or dt.date.today()
    efforts = _effort_vdots(activities, today - dt.timedelta(days=months * 31))
    by_month: dict[str, float] = {}
    for e in efforts:
        m = e["date"][:7]
        by_month[m] = max(by_month.get(m, 0), e["vdot"])
    return [{"month": m, "vdot": round(v, 1)} for m, v in sorted(by_month.items())]


def predictions(activities: list[dict], garmin_pred: dict | None = None, hr_vdot: float | None = None,
                today: dt.date | None = None, window_days: int = 90) -> dict:
    today = today or dt.date.today()
    efforts = _effort_vdots(activities, today - dt.timedelta(days=window_days))
    models: dict[str, dict] = {}

    if efforts:
        best = max(efforts, key=lambda e: e["vdot"])
        models["vdot"] = {"label": "VDOT (Daniels)", "vdot": round(best["vdot"], 1),
                          "source": f"{_(LABEL[best['key']])} {fmt_time(best['time_s'])} ({best['date']})",
                          "times": {k: predict_race_time(best["vdot"], PR_DISTANCES[k]) for k in PREDICT_DISTANCES}}
        # Riegel from the best effort at each distance, choosing the closest distance per target
        best_by_key: dict[str, dict] = {}
        for e in efforts:
            if e["key"] not in best_by_key or e["time_s"] < best_by_key[e["key"]]["time_s"]:
                best_by_key[e["key"]] = e
        riegel = {}
        for k in PREDICT_DISTANCES:
            D = PR_DISTANCES[k]
            src = min(best_by_key.values(), key=lambda e: abs(math.log(D / PR_DISTANCES[e["key"]])))
            riegel[k] = src["time_s"] * (D / PR_DISTANCES[src["key"]]) ** RIEGEL_EXP
        models["riegel"] = {"label": "Riegel", "source": _("best effort at the nearest distance"), "times": riegel}

    if garmin_pred:
        g = {k: garmin_pred.get(f) for k, f in (("5k", "time5K"), ("10k", "time10K"), ("half", "timeHalfMarathon"),
                                                  ("marathon", "timeMarathon")) if garmin_pred.get(f)}
        if g:
            models["garmin"] = {"label": "Garmin", "source": _("watch predictor"), "times": g}

    if hr_vdot:
        models["hr"] = {"label": _("HR (Swain)"), "vdot": round(hr_vdot, 1), "source": _("runs vs HR, rough guide"),
                        "times": {k: predict_race_time(hr_vdot, PR_DISTANCES[k]) for k in PREDICT_DISTANCES}}

    consensus = {}
    for k in PREDICT_DISTANCES:
        vals = [m["times"][k] for m in models.values() if m["times"].get(k)]
        if vals:
            consensus[k] = statistics.median(vals)

    def fmt(times: dict) -> dict:
        return {k: {"seconds": round(t), "time": fmt_time(t), "pace": fmt_time(t / (PR_DISTANCES[k] / 1000))}
                for k, t in times.items()}

    cons_vdot = statistics.median([vdot_from_race(PR_DISTANCES[k], t) for k, t in consensus.items()]) if consensus else None
    return {
        "models": {n: {**m, "times": fmt(m["times"])} for n, m in models.items()},
        "consensus": fmt(consensus),
        "consensus_vdot": round(cons_vdot, 1) if cons_vdot else None,
        "best_effort_vdot": models.get("vdot", {}).get("vdot"),
        "window_days": window_days,
    }
