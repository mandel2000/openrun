"""Training load, readiness and fitness estimation.

- TRIMP (Banister 1991): duration * HRr * 0.64 * e^(1.92 HRr) (men) / 0.86 * e^(1.67 HRr) (women).
- Fitness/fatigue (Banister impulse-response, as CTL/ATL): EWMA 42 d / 7 d; form = CTL - ATL.
- ACWR 7d:28d (Gabbett 2016). Flag > 1.5 as spike. Note: its predictive value is debated
  (Impellizzeri et al. 2020) — we use it only as a soft guard rail.
- HRV-guided readiness (Kiviniemi 2007; Plews et al. 2013; Javaloyes 2019): 7-day rolling
  mean of ln(RMSSD) compared to the 60-day baseline +/- 0.5 SD (smallest worthwhile change).
- Composite readiness score 0-100: HRV (ln RMSSD z-score), resting HR vs baseline, last night's
  sleep, training load (TSB/ACWR) and a 2-question subjective check-in. Subjective wellness reacts
  to load at least as well as objective markers (Saw, Main & Gastin 2016, systematic review), so it
  is weighted next to the physiological ones; missing parts are skipped and weights renormalized.
- VO2max/VDOT estimate from steady runs with HR (Swain 1997: %HRR ~= %VO2R).
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass

from .vdot import vo2_cost


def trimp(duration_min: float, avg_hr: float, rest_hr: float, max_hr: float, sex: str = "male") -> float:
    if not (duration_min and avg_hr and max_hr and max_hr > rest_hr):
        return 0.0
    hrr = max(0.0, min(1.0, (avg_hr - rest_hr) / (max_hr - rest_hr)))
    k, b = (0.86, 1.67) if sex == "female" else (0.64, 1.92)
    return duration_min * hrr * k * math.exp(b * hrr)


def load_series(daily_load: dict[str, float], days: int = 120, end: dt.date | None = None) -> list[dict]:
    """CTL/ATL/TSB + ACWR per day for the last `days` days."""
    end = end or dt.date.today()
    start = end - dt.timedelta(days=days + 42)
    ctl = atl = 0.0
    out, window = [], []
    d = start
    while d <= end:
        load = daily_load.get(d.isoformat(), 0.0)
        ctl += (load - ctl) / 42
        atl += (load - atl) / 7
        window.append(load)
        acute = sum(window[-7:]) / 7
        chronic = sum(window[-28:]) / min(28, len(window))
        if d > end - dt.timedelta(days=days):
            out.append({"date": d.isoformat(), "load": round(load, 1), "ctl": round(ctl, 1), "atl": round(atl, 1),
                        "tsb": round(ctl - atl, 1), "acwr": round(acute / chronic, 2) if chronic > 0 else None})
        d += dt.timedelta(days=1)
    return out


@dataclass
class Readiness:
    status: str  # green | amber | red | unknown
    reasons: list[str]
    hrv_7d: float | None = None
    hrv_baseline: float | None = None
    swc_low: float | None = None
    swc_high: float | None = None
    score: int | None = None
    components: list[dict] | None = None

    def to_dict(self) -> dict:
        return self.__dict__


WEIGHTS = {"hrv": 0.35, "sleep": 0.2, "rhr": 0.15, "load": 0.15, "feel": 0.15}
GARMIN_HRV = {"BALANCED": 75, "UNBALANCED": 50, "LOW": 35, "POOR": 25}
RANK = {"unknown": 0, "green": 1, "amber": 2, "red": 3}


def _clip(x: float) -> int:
    return int(round(max(0.0, min(100.0, x))))


def score_status(score: int) -> str:
    return "green" if score >= 65 else "amber" if score >= 45 else "red"


def readiness(wellness: list[dict], today: dt.date | None = None, load_today: dict | None = None) -> Readiness:
    """wellness rows: {date, hrv_rmssd, rest_hr, sleep_score, sleep_hours, hrv_status, feel, legs};
    load_today: {tsb, acwr} of today (optional)."""
    today = today or dt.date.today()
    rows = sorted((w for w in wellness if w.get("date")), key=lambda w: w["date"])
    hrv = [(w["date"], math.log(w["hrv_rmssd"])) for w in rows if w.get("hrv_rmssd")]
    reasons: list[str] = []
    status = "unknown"
    out = Readiness(status, reasons)
    cutoff60 = (today - dt.timedelta(days=60)).isoformat()
    cutoff7 = (today - dt.timedelta(days=7)).isoformat()
    base = [v for d, v in hrv if d >= cutoff60]
    recent = [v for d, v in hrv if d > cutoff7]
    if len(base) >= 14 and len(recent) >= 3:
        mu, sd = statistics.mean(base), statistics.pstdev(base)
        r7 = statistics.mean(recent)
        lo, hi = mu - 0.5 * sd, mu + 0.5 * sd
        out.hrv_7d, out.hrv_baseline = round(math.exp(r7), 1), round(math.exp(mu), 1)
        out.swc_low, out.swc_high = round(math.exp(lo), 1), round(math.exp(hi), 1)
        if r7 < lo:
            status = "amber"
            reasons.append("HRV media 7d por debajo de tu rango normal: posible fatiga acumulada.")
            if recent[-1] < mu - 1.0 * sd:
                status = "red"
                reasons.append("HRV de hoy muy baja (< -1 SD).")
        else:
            status = "green"
            reasons.append("HRV dentro/encima de tu rango normal.")
    else:
        reasons.append("Faltan datos de HRV (mín. 14 días de base) para valorar la readiness.")

    rhr = [(w["date"], w["rest_hr"]) for w in rows if w.get("rest_hr")]
    base_rhr = [v for d, v in rhr if d >= cutoff60]
    if len(base_rhr) >= 14 and rhr[-1][0] >= cutoff7:
        if rhr[-1][1] >= statistics.mean(base_rhr) + 5:
            reasons.append("FC en reposo +5 ppm sobre tu media: vigila fatiga/enfermedad.")
            status = "amber" if status in ("green", "unknown") else status
    sleep = [w for w in rows if w.get("sleep_score") and w["date"] >= cutoff7]
    if sleep and sleep[-1]["sleep_score"] < 50:
        reasons.append("Sueño pobre anoche.")
        status = "amber" if status in ("green", "unknown") else status
    out.status = status
    _score(out, rows, today, load_today, base, recent)
    return out


def _score(out: Readiness, rows: list[dict], today: dt.date, load_today: dict | None,
           base: list[float], recent: list[float]) -> None:
    """Fill out.score/components and tighten out.status with the composite (never loosens an HRV red)."""
    comps: list[dict] = []
    d0, d1 = today.isoformat(), (today - dt.timedelta(days=1)).isoformat()
    fresh = [w for w in rows if w["date"] in (d0, d1)]
    last = lambda k: next((w[k] for w in reversed(fresh) if w.get(k) is not None), None)  # noqa: E731

    if len(base) >= 14 and recent:
        mu, sd = statistics.mean(base), max(statistics.pstdev(base), 0.03)
        z = 0.5 * (statistics.mean(recent) - mu) / sd + 0.5 * (recent[-1] - mu) / sd
        comps.append({"key": "hrv", "label": "HRV", "score": _clip(70 + 20 * z), "value": f"{math.exp(recent[-1]):.0f} ms"})
    elif last("hrv_status") in GARMIN_HRV:
        comps.append({"key": "hrv", "label": "HRV", "score": GARMIN_HRV[last("hrv_status")], "value": str(last("hrv_status")).lower()})
    if last("sleep_score") is not None:
        comps.append({"key": "sleep", "label": "Sueño", "score": _clip(last("sleep_score")), "value": f"{last('sleep_score'):.0f}/100"})
    elif last("sleep_hours"):
        h = last("sleep_hours")
        comps.append({"key": "sleep", "label": "Sueño", "score": _clip(25 * (h - 4)), "value": f"{h:.1f} h"})
    rhr_base = [w["rest_hr"] for w in rows if w.get("rest_hr") and w["date"] >= (today - dt.timedelta(days=60)).isoformat()]
    if last("rest_hr") and len(rhr_base) >= 7:
        delta = last("rest_hr") - statistics.mean(rhr_base)
        comps.append({"key": "rhr", "label": "FC reposo", "score": _clip(75 - 8 * delta), "value": f"{last('rest_hr'):.0f} ppm" + (f" ({round(delta):+d})" if round(delta) else "")})
    if load_today and load_today.get("tsb") is not None:
        tsb, acwr = load_today["tsb"], load_today.get("acwr")
        sc = 80 if tsb >= -5 else 75 + 2 * (tsb + 5)
        if acwr and acwr > 1.5:
            sc -= 15
        comps.append({"key": "load", "label": "Carga", "score": _clip(sc), "value": f"forma {round(tsb):+d}" + (f" · ACWR {acwr:.2f}" if acwr else "")})
    feel = [w for w in rows if w["date"] == d0 and (w.get("feel") or w.get("legs"))]
    if feel:
        f = feel[-1]
        scale = {1: 15, 2: 35, 3: 60, 4: 80, 5: 95}
        vals = [scale[int(f[k])] for k in ("feel", "legs") if f.get(k) and int(f[k]) in scale]
        if vals:
            comps.append({"key": "feel", "label": "Sensaciones", "score": _clip(sum(vals) / len(vals)), "value": "check-in de hoy"})
        if f.get("sick"):
            out.reasons.append("Has marcado que estás enfermo: hoy descanso o muy suave (regla del cuello).")
            out.status = "red"
    out.components = comps
    if not comps or (len(comps) == 1 and comps[0]["key"] == "load"):
        return
    wsum = sum(WEIGHTS[c["key"]] for c in comps)
    out.score = _clip(sum(WEIGHTS[c["key"]] * c["score"] for c in comps) / wsum)
    st = score_status(out.score)
    if RANK[st] > RANK[out.status] or out.status == "unknown":
        if out.status != "unknown" and st != out.status:
            weak = min(comps, key=lambda c: c["score"])
            out.reasons.append(f"Nota global {out.score}/100: lo que más baja es {weak['label'].lower()} ({weak['value']}).")
        out.status = st


def estimate_vdot_from_run(distance_m: float, duration_s: float, avg_hr: float, rest_hr: float, max_hr: float) -> float | None:
    """VO2max estimate from a steady run. Only meaningful for continuous efforts
    at 60-90% HRR, > 20 min (HR drift and terrain add noise)."""
    if not (distance_m and duration_s and avg_hr and max_hr) or duration_s < 20 * 60:
        return None
    hrr = (avg_hr - rest_hr) / (max_hr - rest_hr)
    if not 0.6 <= hrr <= 0.9:
        return None
    v = distance_m / (duration_s / 60)
    vo2 = vo2_cost(v)
    return (vo2 - 3.5) / hrr + 3.5


def estimate_vdot(activities: list[dict], rest_hr: float, max_hr: float, days: int = 42) -> dict | None:
    """Median VDOT estimate over recent qualifying runs (robust to outliers)."""
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    vals = []
    for a in activities:
        if a.get("date", "") < cutoff or a.get("sport") != "running":
            continue
        v = estimate_vdot_from_run(a.get("distance_m"), a.get("duration_s"), a.get("avg_hr"), rest_hr, max_hr)
        if v and 20 < v < 85:
            vals.append(v)
    if len(vals) < 3:
        return None
    return {"vdot": round(statistics.median(vals), 1), "n_runs": len(vals)}


def hr_zones(max_hr: int, rest_hr: int, lthr: int | None = None) -> list[dict]:
    """5 zones. If LTHR known use Friel %LTHR; otherwise Karvonen %HRR."""
    if lthr:
        bounds = [(0, .85), (.85, .89), (.90, .94), (.95, .99), (1.0, 1.06)]
        return [{"zone": i + 1, "low": round(lthr * a), "high": round(lthr * b)} for i, (a, b) in enumerate(bounds)]
    bounds = [(.50, .60), (.60, .70), (.70, .80), (.80, .90), (.90, 1.0)]
    r = max_hr - rest_hr
    return [{"zone": i + 1, "low": round(rest_hr + r * a), "high": round(rest_hr + r * b)} for i, (a, b) in enumerate(bounds)]


def rmssd(rr_ms: list[float]) -> float | None:
    """RMSSD from RR intervals (ms) with simple artefact filter (>20% change from previous)."""
    clean = [rr_ms[0]] if rr_ms else []
    for rr in rr_ms[1:]:
        if 300 < rr < 2000 and abs(rr - clean[-1]) / clean[-1] < 0.2:
            clean.append(rr)
    if len(clean) < 30:
        return None
    diffs = [(b - a) ** 2 for a, b in zip(clean, clean[1:])]
    return math.sqrt(sum(diffs) / len(diffs))
