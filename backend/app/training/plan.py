"""Evidence-based plan generator.

Principles (see docs/science.md for full references):
- Periodization base -> build -> peak (specific) -> taper (Issurin 2010; Bompa).
- Intensity distribution ~80% low / ~20% moderate-high, max 2 quality sessions/week
  (Seiler & Kjerland 2006; Seiler 2010; Stöggl & Sperlich 2014; Casado et al. 2022).
  Pyramidal emphasis (threshold) in base/build, more polarised (VO2max, race pace) near the
  race (Filipas et al. 2022).
- Volume progression <= ~10%/week with a recovery week every 3rd/4th week; keep the
  acute:chronic ratio <= ~1.3 (Gabbett 2016; Nielsen 2014 for novice injury risk).
- No single session longer than ~10% over the longest run of the previous weeks: single-session
  spikes predict overuse injury better than weekly change (Frandsen et al. 2025, BJSM).
- Taper: reduce volume 40-60% over ~2 weeks (3 for marathon), keep intensity and
  frequency (Bosquet et al. 2007 meta-analysis; Mujika & Padilla 2003).
- Long run <= ~30% weekly volume and time-capped (Daniels); fewer running days -> lower
  sustainable weekly volume and a larger long-run share.
- Variety: each stimulus (hills, fartlek, threshold, VO2max, speed, race pace) has several formats
  that rotate without repeating within ~2 weeks. Any uphill format works (Barnes et al. 2013) and
  short or long intervals both raise VO2max (Billat 2001; Rønnestad 2015); low day-to-day
  variation ("monotony") is linked to illness and staleness (Foster 1998).
- Strength is optional, 1-3x/week on the days the athlete picks. Run first when both fall on the
  same day; heavy legs blunt a hard run for 24-72 h (Doma et al. 2017/2019), so the day before
  a key session gets a lighter session (Blagrove 2018; Llanos-Lagos 2024).
- Training paces from current fitness (VDOT), progressed conservatively toward the goal.
"""

from __future__ import annotations

import datetime as dt
import itertools
import math
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from ..i18n import _
from . import workouts as W
from .vdot import RACE_DISTANCES_M, TrainingPaces, fmt_time, predict_race_time, race_predictions, training_paces, vdot_from_race

Goal = Literal["5k", "10k", "half", "marathon", "base"]
Level = Literal["beginner", "intermediate", "advanced"]

PEAK_VOLUME_KM = {  # typical peak weekly volume by goal/level (Daniels, Pfitzinger, Hudson)
    "5k": {"beginner": 30, "intermediate": 45, "advanced": 65},
    "10k": {"beginner": 35, "intermediate": 50, "advanced": 75},
    "half": {"beginner": 40, "intermediate": 60, "advanced": 85},
    "marathon": {"beginner": 50, "intermediate": 70, "advanced": 100},
    "base": {"beginner": 30, "intermediate": 45, "advanced": 65},
}
LONG_RUN_CAP = {  # (km, minutes)
    "5k": (16, 90), "10k": (20, 105), "half": (24, 130), "marathon": (35, 180), "base": (18, 100),
}
TAPER = {"5k": [0.65], "10k": [0.65], "half": [0.75, 0.55], "marathon": [0.75, 0.6, 0.45], "base": []}
WEEKS_RANGE = {"5k": (6, 16), "10k": (8, 18), "half": (8, 20), "marathon": (12, 24), "base": (4, 16)}
VDOT_GAIN_PER_WEEK = {"beginner": 0.3, "intermediate": 0.2, "advanced": 0.1}  # conservative expected gains

# Default running days when the athlete doesn't pick them, as offsets from a Sunday long run (6).
DEFAULT_RUN_OFFSETS = {1: [6], 2: [2, 6], 3: [1, 3, 6], 4: [1, 3, 5, 6], 5: [1, 2, 3, 5, 6], 6: [0, 1, 2, 3, 5, 6],
                       7: [0, 1, 2, 3, 4, 5, 6]}
# Sustainable share of the typical peak volume by running days/week: with few days each run would
# otherwise get too long (session spikes) or too intense.
FREQ_VOLUME = {1: 0.35, 2: 0.55, 3: 0.7, 4: 0.85, 5: 0.95, 6: 1.0, 7: 1.0}
MIN_START_KM = {1: 5, 2: 8, 3: 12, 4: 16, 5: 20, 6: 25, 7: 30}
LONG_SHARE = {1: 1.0, 2: 0.55, 3: 0.33, 4: 0.30, 5: 0.28, 6: 0.26, 7: 0.25}
SESSION_SPIKE = 1.10  # max ratio vs the longest run so far (Frandsen 2025)


@dataclass
class PlanRequest:
    goal: Goal
    start_date: dt.date
    days_per_week: int = 4
    long_run_day: int = 6  # 0=Mon .. 6=Sun
    current_weekly_km: float = 20
    longest_recent_run_km: float = 10
    level: Level = "intermediate"
    recent_race_distance: str | None = None  # key of RACE_DISTANCES_M
    recent_race_time_s: float | None = None
    vdot: float | None = None
    race_date: dt.date | None = None
    weeks: int | None = None
    goal_time_s: float | None = None
    age: int | None = None
    include_strength: bool = False
    name: str | None = None
    run_days: list[int] | None = None  # weekdays 0=Mon..6=Sun; overrides days_per_week
    strength_days: list[int] | None = None  # weekdays for strength (when include_strength)
    max_weekly_km: float | None = None  # athlete's own weekly ceiling
    hills: bool = True  # has hills nearby (else hill sessions are swapped for fartlek/speed)
    seed: int | None = None  # varies session choice between athletes, stable for the same request


@dataclass
class PlanWeek:
    index: int
    phase: str
    target_km: float
    vdot: float
    workouts: list[W.Workout] = field(default_factory=list)
    is_recovery: bool = False

    def to_dict(self) -> dict:
        run_km = sum(w.distance_km for w in self.workouts)
        runs = [w for w in self.workouts if w.sport == "running" and w.type != "race"]
        tot = sum(w.duration_min for w in runs)
        low = sum(w.low_intensity_min for w in runs)
        return {
            "index": self.index, "phase": self.phase, "target_km": round(self.target_km, 1),
            "planned_km": round(run_km, 1), "vdot": round(self.vdot, 1), "is_recovery": self.is_recovery,
            "low_intensity_pct": round(100 * low / tot) if tot else 100,
            "workouts": [w.to_dict() for w in self.workouts],
        }


def _phase_split(n_weeks: int, goal: Goal) -> list[str]:
    taper_n = len(TAPER[goal])
    if goal == "base":
        return ["base"] * n_weeks
    work = n_weeks - taper_n
    base_n = max(2, round(work * 0.4))
    peak_n = max(2, round(work * 0.25))
    build_n = max(1, work - base_n - peak_n)
    return ["base"] * base_n + ["build"] * build_n + ["peak"] * peak_n + ["taper"] * taper_n


def _volumes(req: PlanRequest, phases: list[str], peak: float, n_days: int) -> tuple[list[float], list[bool]]:
    vol = max(req.current_weekly_km, MIN_START_KM[n_days])
    if req.max_weekly_km:
        vol = min(vol, req.max_weekly_km)
    deload_every = 3 if (req.age or 0) >= 50 or req.level == "beginner" else 4
    vols, recov = [], []
    taper_ix = 0
    last_load = vol
    block_week = 0
    for i, ph in enumerate(phases):
        if ph == "taper":
            vols.append(round(last_load * TAPER[req.goal][taper_ix], 1))
            recov.append(False)
            taper_ix += 1
            continue
        block_week += 1
        if block_week == deload_every:
            block_week = 0
            vols.append(round(last_load * 0.75, 1))  # recovery week (-25%)
            recov.append(True)
            continue
        if i > 0:
            vol = min(peak, last_load * 1.08)  # <= 10%/week (Nielsen 2014; Gabbett 2016 ACWR <= 1.3)
        last_load = vol
        vols.append(round(vol, 1))
        recov.append(False)
    return vols, recov


def _circ(a: int, b: int) -> int:
    d = abs(a - b) % 7
    return min(d, 7 - d)


def day_roles(run_days: list[int], long_day: int, n_q: int) -> dict[int, str]:
    """Give each running day a role: L (long), Q1/Q2 (quality), E (easy), R (recovery).

    Hard days are spread as far apart as possible (hard/easy principle) and never the day before
    the long run if it can be avoided; Q1 is the first quality day after the long run."""
    days = sorted(set(run_days))
    roles = {long_day: "L"}
    others = [d for d in days if d != long_day]
    n_q = min(n_q, len(others))
    best: tuple | None = None
    for combo in itertools.combinations(others, n_q):
        pts = [long_day, *combo]
        spread = min((_circ(a, b) for a, b in itertools.combinations(pts, 2)), default=7)
        before_long = sum(1 for q in combo if (long_day - q) % 7 == 1)
        key = (spread, -before_long, -sum((q - long_day) % 7 for q in combo))
        if best is None or key > best[0]:
            best = (key, combo)
    qs = sorted(best[1] if best else (), key=lambda q: (q - long_day) % 7)
    for i, q in enumerate(qs):
        roles[q] = f"Q{i + 1}"
    after_long = (long_day + 1) % 7
    for d in others:
        if d not in roles:
            roles[d] = "R" if len(days) >= 6 and d == after_long else "E"
    return roles


# ---------------------------------------------------------------- session selection


@dataclass
class _Ctx:
    goal: str
    paces: TrainingPaces
    weekly_km: float
    budget_km: float  # longest session allowed this week (session-spike rule)
    hills: bool

    @property
    def t_km(self) -> float:  # threshold <= 10% weekly (Daniels)
        return max(3.0, 0.10 * self.weekly_km)

    @property
    def i_km(self) -> float:  # interval <= min(10 km, 8% weekly)
        return max(2.4, min(10.0, 0.08 * self.weekly_km))

    @property
    def r_km(self) -> float:  # repetition <= min(8 km, 5% weekly)
        return max(1.6, min(8.0, 0.05 * self.weekly_km))

    @property
    def t_min(self) -> int:
        return min(30, max(12, round(self.t_km * self.paces.threshold.mid() / 60)))


Builder = Callable[[int, float], W.Workout]  # (times used before, dose scale 0-1) -> workout
RACE_ZONE = {"5k": ("five_k", "5K"), "10k": ("ten_k", "10K"), "half": ("half", None), "marathon": ("marathon", None)}
RACE_SETS = {  # (reps, metres, rest s) at goal pace, peak phase
    "5k": [(5, 1000, 150), (6, 800, 120), (4, 1200, 180), (3, 1600, 180)],
    "10k": [(5, 1600, 90), (4, 2000, 90), (6, 1000, 60), (3, 3000, 120)],
    "half": [(3, 3000, 120), (3, 4000, 120), (4, 2000, 90), (2, 5000, 150)],
    "marathon": [(2, 5000, 180), (3, 4000, 120), (2, 6000, 180), (2, 7000, 180)],
}
TAPER_SETS = {  # short sharpening sets at goal pace (Bosquet 2007: keep intensity, cut volume)
    "fast": [(3, 1000, 90), (2, 1600, 120), (5, 600, 60)],
    "slow": [(3, 1000, 90), (2, 2000, 120), (2, 3000, 120)],
}


def _label(goal: str) -> str:
    zone, label = RACE_ZONE[goal]
    return label or (_("half marathon") if goal == "half" else _("marathon"))


def _families(c: _Ctx) -> dict[str, list[tuple[str, Builder]]]:
    P, wk = c.paces, c.weekly_km

    def n(base: float, s: float, lo: int = 2) -> int:
        return max(lo, round(base * s))

    t_pace, i_pace = P.threshold.mid(), P.interval.mid()
    t_total = min(40, round(c.t_km * t_pace / 60))
    i_total_s = c.i_km * i_pace
    cruise_rep = 1000 if c.t_km < 6 else 1600 if c.t_km < 9 else 2000
    fam: dict[str, list[tuple[str, Builder]]] = {
        "hills": [
            ("hill_sprints", lambda k, s: W.hill_sprints(P, wk * 0.16 * s + 1, n(6 + 2 * min(k, 2), s, 4))),
            ("hills_60", lambda k, s: W.hills(P, n(6 + 2 * min(k, 2), s, 4), 60)),
            ("hills_90", lambda k, s: W.hills(P, n(5 + min(k, 3), s, 3), 90)),
            ("long_hills", lambda k, s: W.long_hills(P, n(4 + min(k, 2), s, 3), 150 if k < 2 else 180)),
        ],
        "fartlek": [
            ("fartlek_classic", lambda k, s: W.fartlek(P, "classic", n(8 + 2 * min(k, 2), s, 5))),
            ("fartlek_pyramid", lambda k, s: W.fartlek(P, "pyramid", 2 if (k and s >= 1 and wk >= 35) else 1)),
            ("fartlek_mona", lambda k, s: W.fartlek(P, "mona")),
        ],
        "aerobic": [
            ("progression", lambda k, s: W.progression_run(P, max(5, wk * 0.18 * s))),
            ("progressive_tempo", lambda k, s: W.progressive_tempo(P, max(12, round((c.t_min - 2) * s)))),
            ("tempo_short", lambda k, s: W.tempo(P, max(10, round((c.t_min - 8) * s)))),
        ],
        "threshold": [
            ("cruise", lambda k, s: W.cruise_intervals(P, n(c.t_km * 1000 / cruise_rep, s, 3), cruise_rep)),
            ("tempo", lambda k, s: W.tempo(P, max(12, round(c.t_min * s)))),
            ("split_tempo", lambda k, s: W.split_tempo(P, 2 if t_total < 27 else 3,
                                                       max(6, round(t_total * s / (2 if t_total < 27 else 3))))),
            ("progressive_tempo", lambda k, s: W.progressive_tempo(P, max(16, round((c.t_min + 6) * s)))),
        ],
        "vo2": [
            ("vo2_dist", lambda k, s: W.vo2_intervals(P, n(c.i_km * 1000 / [800, 1000, 1200][k % 3], s, 3), [800, 1000, 1200][k % 3])),
            ("vo2_time", lambda k, s: W.vo2_time(P, max(3, min(6, round(i_total_s * s / 180))), 3)),
            ("short_30_30", lambda k, s: W.short_intervals(P, 2 if c.i_km < 4 else 3, max(6, min(10, round(c.i_km * 1000 * s / (30 / i_pace * 1000) / 2))))),
        ],
        "speed": [
            ("reps_200", lambda k, s: W.repetitions(P, max(6, min(12, n(c.r_km * 1000 / 200, s, 6))), 200)),
            ("reps_400", lambda k, s: W.repetitions(P, max(5, min(10, n(c.r_km * 1000 / 400, s, 5))), 400)),
        ],
        "recovery": [
            ("strides", lambda k, s: W.easy_with_strides(P, wk * 0.15)),
            ("fartlek_light", lambda k, s: W.fartlek(P, "classic", 6)),
            ("progression_light", lambda k, s: W.progression_run(P, max(5, wk * 0.15 * s))),
        ],
        "strides": [("strides", lambda k, s: W.easy_with_strides(P, wk * 0.15))],
    }
    if c.i_km >= 3.4:  # a full pyramid fits Daniels' I-volume limit
        fam["vo2"].append(("vo2_pyramid", lambda k, s: W.vo2_pyramid(P, 1200 if c.i_km >= 3.6 and s >= 1 else 800)))
    if c.hills:
        fam["speed"].append(("hill_sprints", fam["hills"][0][1]))
        fam["threshold"].append(("long_hills", fam["hills"][3][1]))
    else:
        fam["hills"] = fam["fartlek"]
    if c.goal in RACE_ZONE:
        zone = RACE_ZONE[c.goal][0]
        def race_set(r: tuple[int, int, int]) -> Builder:
            def build(k: int, s: float) -> W.Workout:
                reps = max(2, round(r[0] * s))
                metres = max(1000, round(r[0] * r[1] * s / reps / 500) * 500)  # shorter reps once at 2
                return W.race_pace_intervals(P, zone, reps, min(metres, r[1]), r[2], _label(c.goal))
            return build
        fam["race"] = [(f"race_{i}", race_set(r)) for i, r in enumerate(RACE_SETS[c.goal])]
        def taper_set(r: tuple[int, int, int]) -> Builder:
            return lambda k, s: W.race_pace_intervals(P, zone, r[0], r[1], r[2], _label(c.goal))
        fam["taper"] = [(f"taper_{i}", taper_set(r)) for i, r in enumerate(TAPER_SETS["fast" if c.goal in ("5k", "10k") else "slow"])]
    else:
        fam["race"] = fam["threshold"]
        fam["taper"] = fam["strides"]
    return fam


class _Picker:
    """Rotates session formats: least-used first, never the same format within 2 weeks if avoidable,
    hills at most every other week. The order of formats is shuffled per athlete (seed)."""

    def __init__(self, seed: int | None) -> None:
        self.rng = random.Random(seed or 0)
        self.order: dict[str, list[str]] = {}
        self.uses: Counter[str] = Counter()
        self.recent: list[tuple[int, str]] = []
        self.hill_week = -9

    def pick(self, family: str, c: _Ctx, week: int, avoid: set[str] | None = None) -> W.Workout:
        fams = _families(c)
        if family == "hills" and c.hills and week - self.hill_week < 2:
            family = "fartlek"
        variants = dict(fams[family])
        if family not in self.order:
            o = list(variants)
            self.rng.shuffle(o)
            self.order[family] = o
        order = [x for x in self.order[family] if x in variants] + [x for x in variants if x not in self.order[family]]
        recent = {x for w, x in self.recent if week - w <= 2} | (avoid or set())
        name = min(order, key=lambda x: (x in recent, self.uses[x], order.index(x)))
        k = self.uses[name]
        self.uses[name] += 1
        self.recent.append((week, name))
        if family == "hills" or name in ("hill_sprints", "long_hills"):
            self.hill_week = week
        w = None
        for s in (1.0, 0.8, 0.65, 0.5, 0.35):  # shrink the dose until it fits the session-spike budget
            w = variants[name](k, s)
            if w.distance_km <= c.budget_km:
                break
        w.variant = name  # type: ignore[attr-defined]
        return w


QUALITY_PLAN: dict[str, dict[str, list[list[str]]]] = {
    # phase -> goal -> per-week rotation of [Q1, Q2] families (single-quality weeks use the first)
    "base": {
        "5k": [["hills", "aerobic"], ["fartlek", "aerobic"], ["speed", "aerobic"]],
        "10k": [["hills", "aerobic"], ["fartlek", "aerobic"], ["speed", "aerobic"]],
        "*": [["hills", "aerobic"], ["fartlek", "aerobic"]],
    },
    "build": {
        "5k": [["vo2", "threshold"], ["vo2", "speed"], ["threshold", "vo2"]],
        "10k": [["vo2", "threshold"], ["threshold", "speed"], ["vo2", "threshold"]],
        "*": [["threshold", "vo2"], ["threshold", "speed"], ["threshold", "vo2"]],
    },
    "peak": {
        "5k": [["race", "vo2"], ["race", "speed"]],
        "10k": [["race", "threshold"], ["race", "vo2"]],
        "half": [["race", "vo2"], ["race", "threshold"]],
        "marathon": [["race", "threshold"]],
        "*": [["threshold", "vo2"]],
    },
    "taper": {"*": [["taper", "strides"]]},
}
# With a single quality session per week, alternate the main stimuli week to week.
SINGLE_QUALITY = {
    "base": ["hills", "aerobic", "fartlek"],
    "build": ["threshold", "vo2"],
    "peak": ["race", "threshold", "race", "vo2"],
    "taper": ["taper"],
}


def _quality_sessions(picker: _Picker, c: _Ctx, phase: str, wk_in_phase: int, n_q: int, level: Level,
                      recovery: bool, week: int) -> list[W.Workout]:
    if n_q <= 0:
        return []
    if recovery:
        return [picker.pick("recovery", c, week) for _i in range(n_q)]
    if phase == "base" and level == "beginner" and wk_in_phase < 2:
        return [W.easy_with_strides(c.paces, c.weekly_km * 0.18), W.easy_with_strides(c.paces, c.weekly_km * 0.15, 4)][:n_q]
    if n_q == 1:
        rot = SINGLE_QUALITY[phase]
        if c.goal == "base" and phase != "base":
            rot = ["threshold", "vo2"]
        return [picker.pick(rot[wk_in_phase % len(rot)], c, week)]
    table = QUALITY_PLAN[phase]
    rot = table.get(c.goal, table["*"])
    fams = rot[wk_in_phase % len(rot)]
    first = picker.pick(fams[0], c, week)
    second = picker.pick(fams[1], c, week, avoid={getattr(first, "variant", "")})
    return [first, second]


def _long_style(goal: str, phase: str, n_days: int, wk_in_phase: int, is_rec: bool, level: Level) -> tuple[str, float]:
    """(style, fast-finish share). Long runs vary too: easy, + strides, with surges, progressive,
    or with a goal-pace finish (specificity, Pfitzinger/Canova) for half and marathon."""
    if is_rec or phase == "taper":
        return "easy", 0
    if phase == "base":
        return ("strides" if wk_in_phase % 2 else "easy"), 0
    if goal in ("half", "marathon") and phase == "peak" and wk_in_phase % 2 == 1:
        if n_days >= 4:  # with fewer days the quality session already carries race pace (80/20)
            return "fast", 0.4 if goal == "marathon" else 0.3
        return "surges", 0
    if n_days == 1:  # the only run of the week carries the stimulus
        return ["surges", "progressive", "easy"][wk_in_phase % 3], 0
    if n_days <= 3:
        return ["easy", "surges"][wk_in_phase % 2], 0
    if goal in ("half", "marathon") and phase == "build" and wk_in_phase % 3 == 2 and level != "beginner":
        return "progressive", 0
    return ("surges" if phase == "build" and wk_in_phase % 3 == 1 else "easy"), 0


def _week_dates(start: dt.date, week_index: int) -> list[dt.date]:
    monday = start - dt.timedelta(days=start.weekday()) + dt.timedelta(weeks=week_index)
    return [monday + dt.timedelta(days=i) for i in range(7)]


def resolve_vdot(req: PlanRequest) -> float:
    if req.vdot:
        return req.vdot
    if req.recent_race_distance and req.recent_race_time_s:
        return vdot_from_race(RACE_DISTANCES_M[req.recent_race_distance], req.recent_race_time_s)
    # Fallback estimate from level when no race data (user should do a time trial in week 1-2)
    return {"beginner": 32.0, "intermediate": 42.0, "advanced": 52.0}[req.level]


def _strength(req: PlanRequest, week_runs: dict[int, W.Workout], phase: str, is_rec: bool, dates: list[dt.date]) -> list[W.Workout]:
    focus = "base" if phase == "base" else "build" if phase == "build" else "maintenance"
    key_days = {d for d, w in week_runs.items() if w and (w.intensity in ("moderate", "high") or w.type == "long")}
    if req.strength_days:
        days = sorted(set(d % 7 for d in req.strength_days))[:3]
    else:  # default: on the quality days (hard days hard, easy days easy)
        days = [d for d, w in week_runs.items() if w and w.intensity in ("moderate", "high") and w.type != "long"][:2]
    if phase == "peak" or is_rec:
        days = days[:max(1, len(days) - 1)]
    out = []
    for d in days:
        before_key = (d + 1) % 7 in key_days
        s = W.strength_session("maintenance" if before_key else focus)
        if d in week_runs and week_runs[d]:
            s.description += " " + _("Run first, then strength (Doma & Deakin 2013: less interference with the run).")
        if before_key:
            s.description += " " + _("Tomorrow is a key session: lighter strength today, no jumps or heavy legs (residual fatigue lasts 24-72 h).")
        s.date = dates[d].isoformat()
        s.phase = phase
        out.append(s)
    return out


def generate_plan(req: PlanRequest) -> dict:
    if req.run_days:
        run_days = sorted(set(int(d) % 7 for d in req.run_days))
        req.days_per_week = len(run_days)
    if req.days_per_week not in DEFAULT_RUN_OFFSETS:
        raise ValueError("days_per_week must be 1..7")
    if not req.run_days:
        run_days = sorted((off - 6 + req.long_run_day) % 7 for off in DEFAULT_RUN_OFFSETS[req.days_per_week])
    if req.long_run_day not in run_days:
        req.long_run_day = run_days[-1]
    n_days = req.days_per_week
    lo, hi = WEEKS_RANGE[req.goal]
    if req.race_date:
        first_monday = req.start_date - dt.timedelta(days=req.start_date.weekday())
        n_weeks = (req.race_date - first_monday).days // 7 + 1
    else:
        n_weeks = req.weeks or {"5k": 8, "10k": 10, "half": 12, "marathon": 16, "base": 8}[req.goal]
    warnings: list[str] = []
    if n_weeks < lo:
        warnings.append(_("Short plan ({n} weeks). At least {lo} weeks are recommended for {goal}.", n=n_weeks, lo=lo, goal=req.goal))
    if n_weeks > hi and req.race_date:
        # Too far out: start the specific plan later; until then the athlete does base running.
        race_monday = req.race_date - dt.timedelta(days=req.race_date.weekday())
        req.start_date = race_monday - dt.timedelta(weeks=hi - 1)
        warnings.append(_("Race far away: the plan starts on {date} ({n} weeks). Until then, base running.", date=req.start_date.isoformat(), n=hi))
    n_weeks = max(min(n_weeks, hi), min(lo, n_weeks), 2)

    vdot0 = resolve_vdot(req)
    goal_vdot = None
    if req.goal_time_s and req.goal != "base":
        goal_vdot = vdot_from_race(RACE_DISTANCES_M[req.goal], req.goal_time_s)
        attainable = vdot0 + VDOT_GAIN_PER_WEEK[req.level] * n_weeks
        if goal_vdot > attainable + 0.5:
            pred = predict_race_time(attainable, RACE_DISTANCES_M[req.goal])
            warnings.append(_("Ambitious goal: goal VDOT {goal} vs current {now}. A realistic prediction at the end of the "
                              "plan is ~{pred}. Paces will adjust to your actual results.",
                              goal=f"{goal_vdot:.1f}", now=f"{vdot0:.1f}", pred=fmt_time(pred)))
    if not (req.recent_race_distance or req.vdot):
        warnings.append(_("No recent race: paces are estimated. Do a 5K or 30' test in week 1-2 to calibrate."))
    if n_days <= 2 and req.goal in ("half", "marathon"):
        warnings.append(_("With {n} running day(s) a week the plan stays conservative: for a {goal} at least 3 days are recommended.",
                          n=n_days, goal=_label(req.goal)))

    cap_km, cap_min = LONG_RUN_CAP[req.goal]
    peak = max(PEAK_VOLUME_KM[req.goal][req.level] * FREQ_VOLUME[n_days], req.current_weekly_km)
    if req.max_weekly_km:
        if req.max_weekly_km < PEAK_VOLUME_KM[req.goal]["beginner"] * FREQ_VOLUME[n_days] * 0.7:
            warnings.append(_("Your weekly limit ({km} km) is low for this goal: the plan respects it, but expect a more modest result.",
                              km=f"{req.max_weekly_km:g}"))
        peak = min(peak, req.max_weekly_km)
    phases = _phase_split(n_weeks, req.goal)
    vols, recov = _volumes(req, phases, peak, n_days)
    if req.max_weekly_km:
        vols = [min(v, req.max_weekly_km) for v in vols]
    L = req.long_run_day
    n_q_default = 0 if n_days == 1 else 1 if n_days <= 3 or (req.level == "beginner" and n_days <= 4) else 2
    roles = day_roles(run_days, L, n_q_default)
    long_share = LONG_SHARE[n_days]
    if req.goal == "marathon" and n_days >= 3:  # marathoners need 28-35 km long runs (Pfitzinger/Hudson)
        long_share = max(long_share, 0.36)
    picker = _Picker(req.seed)

    weeks: list[PlanWeek] = []
    phase_counter: dict[str, int] = {}
    prev_long = max(req.longest_recent_run_km or 0, 3.0)
    for wi, (phase, vol, is_rec) in enumerate(zip(phases, vols, recov)):
        # Paces progress conservatively toward goal fitness; re-calibrate from real results.
        vdot = vdot0 + VDOT_GAIN_PER_WEEK[req.level] * wi * 0.5
        if goal_vdot:
            vdot = min(vdot, max(goal_vdot, vdot0))
        paces = training_paces(vdot)
        wk_in_phase = phase_counter.get(phase, 0)
        phase_counter[phase] = wk_in_phase + 1
        dates = _week_dates(req.start_date, wi)
        is_race_week = req.goal != "base" and wi == n_weeks - 1
        spike_cap = prev_long * SESSION_SPIKE

        # Long run: share of the week, time + distance capped, and <= +10% vs the longest run so far.
        long_cap_by_time = cap_min * 60 / paces.long.mid()
        share = long_share + (0.06 if req.goal == "marathon" and phase == "peak" and n_days >= 3 else 0)
        long_km = min(vol * share, cap_km, long_cap_by_time, spike_cap)
        if is_rec or phase == "taper":
            long_km = min(long_km, prev_long * 0.75 if is_rec else vol * long_share)
        long_km = max(long_km, 3)

        n_q = n_q_default
        # a quality session never outgrows the spike limit nor ~a quarter of the week
        ctx = _Ctx(req.goal, paces, vol, max(min(spike_cap, vol * 0.25), 6.0), req.hills)
        quality = _quality_sessions(picker, ctx, phase, wk_in_phase, n_q, req.level, is_rec, wi)
        n_easy = sum(1 for r in roles.values() if r in ("E", "R")) + sum(1 for i in range(len(quality), n_q) if f"Q{i + 1}" in roles.values())
        q_km = sum(q.distance_km for q in quality)
        # Few days: give the long run the volume the easy runs can't take (still within all caps).
        if n_easy and not is_rec and phase != "taper":
            ideal = (vol - q_km) / (1 + 0.85 * n_easy)
            long_km = max(long_km, min(ideal, cap_km, long_cap_by_time, spike_cap))
        elif not n_easy and not is_rec and phase != "taper":
            long_km = max(long_km, min(vol - q_km, cap_km, long_cap_by_time, spike_cap))
        if not is_rec and phase != "taper":
            long_km = max(long_km, min(prev_long, cap_km, long_cap_by_time))  # don't shrink the long run mid-block
            prev_long = max(prev_long, long_km)

        long_km = math.floor(long_km * 2) / 2  # round down: never round past the spike limit
        style, fast_share = _long_style(req.goal, phase, n_days, wk_in_phase, is_rec, req.level)
        if style == "fast":
            fast_zone = "marathon" if req.goal == "marathon" else "half"
            lw = W.long_run(paces, long_km, fast_finish_km=round(min(16 if req.goal == "marathon" else 8, long_km * fast_share)),
                            fast_zone=fast_zone)
        else:
            lw = W.long_run(paces, long_km, style=style)
        if lw.intensity != "low" and len(quality) > 1:
            # Long run already carries race-pace work: keep only 2 hard days/week (80/20)
            quality[1] = W.easy_with_strides(paces, vol * 0.15)

        assigned: dict[int, W.Workout | None] = {}
        easy_days: list[tuple[int, str]] = []
        for day, role in roles.items():
            if role == "L":
                assigned[day] = lw
            elif role in ("Q1", "Q2") and int(role[1]) <= len(quality):
                assigned[day] = quality[int(role[1]) - 1]
            else:
                easy_days.append((day, "R" if role == "R" else "E"))

        used = sum(w.distance_km for w in assigned.values() if w)
        remaining = max(0.0, vol - used)
        if easy_days:
            per = max(3.0, min(remaining / len(easy_days), long_km * 0.85, spike_cap))
            for day, kind in easy_days:
                assigned[day] = W.recovery_run(paces, per * 0.8) if kind == "R" else W.easy_run(paces, per)

        if is_race_week:
            race_day = (req.race_date or dates[L]).weekday()
            dist = RACE_DISTANCES_M[req.goal]
            zone = {"5k": "five_k", "10k": "ten_k", "half": "half", "marathon": "marathon"}[req.goal]
            assigned = {d: w for d, w in assigned.items() if d < race_day - 1 and w and w.type not in ("long",)}
            shake = n_days >= 3 and race_day >= 1
            # keep a short sharpening session first, then easy runs
            keep = sorted(assigned, key=lambda d: (assigned[d].intensity == "low", d))[: max(0, n_days - (2 if shake else 1))]
            assigned = {d: assigned[d] for d in keep}
            if shake:
                assigned[race_day - 1] = W.shakeout(paces)
            assigned[race_day] = W.race(paces, req.goal, dist, zone)
            if not req.race_date:  # no target race: end with a time trial to re-calibrate VDOT
                assigned[race_day].title = f"🏁 Test {req.goal.upper()} (contrarreloj)"

        week = PlanWeek(wi + 1, phase, vol if n_days > 1 else round(long_km, 1), vdot, is_recovery=is_rec)
        for day in sorted(d for d, w in assigned.items() if w):
            w = assigned[day]
            w.date = dates[day].isoformat()
            w.phase = phase
            week.workouts.append(w)

        if req.include_strength and phase != "taper" and not is_race_week:
            week.workouts += _strength(req, assigned, phase, is_rec, dates)
            week.workouts.sort(key=lambda w: (w.date, w.sport != "running"))
        weeks.append(week)

    final_vdot = weeks[-1].vdot
    return {
        "name": req.name or f"Plan {req.goal} ({n_weeks} semanas)",
        "goal": req.goal,
        "level": req.level,
        "start_date": _week_dates(req.start_date, 0)[0].isoformat(),
        "race_date": req.race_date.isoformat() if req.race_date else None,
        "goal_time": fmt_time(req.goal_time_s) if req.goal_time_s else None,
        "days_per_week": n_days,
        "run_days": run_days,
        "long_run_day": L,
        "strength_days": sorted(set(d % 7 for d in req.strength_days)) if req.include_strength and req.strength_days else None,
        "max_weekly_km": req.max_weekly_km,
        "hills": req.hills,
        "vdot_start": round(vdot0, 1),
        "vdot_goal": round(goal_vdot, 1) if goal_vdot else None,
        "paces_start": training_paces(vdot0).as_dict(),
        "predictions_start": race_predictions(vdot0),
        "predictions_end": race_predictions(final_vdot),
        "warnings": warnings,
        "weeks": [w.to_dict() for w in weeks],
    }
