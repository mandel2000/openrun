"""Daniels & Gilbert VDOT model.

References:
- Daniels J, Gilbert J. "Oxygen Power: Performance Tables for Distance Runners" (1979).
- Daniels J. "Daniels' Running Formula", 3rd ed. (2014) — training intensities as %VDOT.

VO2 cost of running at velocity v (m/min):
    VO2 = -4.60 + 0.182258 v + 0.000104 v^2
Fraction of VO2max sustainable for t minutes:
    %max = 0.8 + 0.1894393 e^(-0.012778 t) + 0.2989558 e^(-0.1932605 t)
VDOT = VO2 / %max
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RACE_DISTANCES_M = {
    "1500": 1500.0,
    "mile": 1609.344,
    "3k": 3000.0,
    "5k": 5000.0,
    "10k": 10000.0,
    "15k": 15000.0,
    "half": 21097.5,
    "marathon": 42195.0,
}


def vo2_cost(v_m_min: float) -> float:
    return -4.60 + 0.182258 * v_m_min + 0.000104 * v_m_min**2


def pct_max(t_min: float) -> float:
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot_from_race(distance_m: float, time_s: float) -> float:
    t_min = time_s / 60.0
    v = distance_m / t_min
    return vo2_cost(v) / pct_max(t_min)


def velocity_for_vo2(vo2: float) -> float:
    """Inverse of vo2_cost: velocity (m/min) that costs `vo2` ml/kg/min."""
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def predict_race_time(vdot: float, distance_m: float) -> float:
    """Race time (s) for which the VDOT equation equals `vdot` (bisection)."""
    lo, hi = distance_m / 1000 * 60, distance_m / 1000 * 60 * 20  # 1:00/km .. 20:00/km
    for _ in range(100):
        mid = (lo + hi) / 2
        if vdot_from_race(distance_m, mid) > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def pace_s_per_km_at_fraction(vdot: float, fraction: float) -> float:
    v = velocity_for_vo2(vdot * fraction)
    return 1000.0 / v * 60.0


@dataclass(frozen=True)
class PaceRange:
    slow: float  # s/km
    fast: float  # s/km

    def mid(self) -> float:
        return (self.slow + self.fast) / 2

    def as_dict(self) -> dict:
        return {"slow": round(self.slow), "fast": round(self.fast), "slow_fmt": fmt_pace(self.slow), "fast_fmt": fmt_pace(self.fast)}


@dataclass(frozen=True)
class TrainingPaces:
    vdot: float
    easy: PaceRange
    long: PaceRange
    marathon: PaceRange
    half: PaceRange
    threshold: PaceRange
    ten_k: PaceRange
    five_k: PaceRange
    interval: PaceRange
    repetition: PaceRange
    recovery: PaceRange

    def as_dict(self) -> dict:
        out = {"vdot": round(self.vdot, 1)}
        for k in ("recovery", "easy", "long", "marathon", "half", "threshold", "ten_k", "five_k", "interval", "repetition"):
            out[k] = getattr(self, k).as_dict()
        return out

    def get(self, zone: str) -> PaceRange:
        return getattr(self, zone)


def _race_pace(vdot: float, key: str) -> float:
    d = RACE_DISTANCES_M[key]
    return predict_race_time(vdot, d) / (d / 1000)


def training_paces(vdot: float) -> TrainingPaces:
    """Training paces as fractions of VDOT (Daniels' Running Formula):
    E 59-74%, M ~ predicted marathon pace, T 83-88%, I 95-100%, R ~ 105-110%."""
    f = lambda x: pace_s_per_km_at_fraction(vdot, x)  # noqa: E731
    mp, hmp, tkp, fkp = (_race_pace(vdot, k) for k in ("marathon", "half", "10k", "5k"))
    return TrainingPaces(
        vdot=vdot,
        recovery=PaceRange(f(0.59) + 15, f(0.59)),
        easy=PaceRange(f(0.62), f(0.72)),
        long=PaceRange(f(0.64), f(0.74)),
        marathon=PaceRange(mp + 4, mp - 4),
        half=PaceRange(hmp + 3, hmp - 3),
        threshold=PaceRange(f(0.86), f(0.88)),
        ten_k=PaceRange(tkp + 3, tkp - 3),
        five_k=PaceRange(fkp + 3, fkp - 3),
        interval=PaceRange(f(0.975), f(1.0)),
        repetition=PaceRange(f(1.05), f(1.08)),
    )


def fmt_pace(s_per_km: float) -> str:
    s = int(round(s_per_km))
    return f"{s // 60}:{s % 60:02d}"


def fmt_time(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def parse_time(text: str) -> float:
    """'h:mm:ss' | 'mm:ss' -> seconds."""
    parts = [float(p) for p in text.strip().split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def race_predictions(vdot: float) -> dict:
    return {
        k: {"seconds": round(t := predict_race_time(vdot, d)), "time": fmt_time(t), "pace": fmt_pace(t / (d / 1000))}
        for k, d in RACE_DISTANCES_M.items()
        if k in ("5k", "10k", "half", "marathon")
    }
