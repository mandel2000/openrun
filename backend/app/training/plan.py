"""Evidence-based plan generator.

Principles (see docs/RESEARCH.md for full references):
- Periodization base -> build -> peak (specific) -> taper (Issurin 2010; Bompa).
- Intensity distribution ~80% low / ~20% moderate-high, max 2 quality sessions/week
  (Seiler & Kjerland 2006; Seiler 2010; Stöggl & Sperlich 2014; Casado et al. 2022).
- Volume progression <= ~10%/week with a recovery week every 3rd/4th week; keep the
  acute:chronic ratio <= ~1.3 (Gabbett 2016; Nielsen 2014 for novice injury risk).
- Taper: reduce volume 40-60% over ~2 weeks (3 for marathon), keep intensity and
  frequency (Bosquet et al. 2007 meta-analysis; Mujika & Padilla 2003).
- Long run <= ~30% weekly volume and time-capped (Daniels).
- Strength training 2x/week improves running economy (Blagrove et al. 2018).
- Training paces from current fitness (VDOT), progressed conservatively toward the goal.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal

from . import workouts as W
from .vdot import RACE_DISTANCES_M, fmt_time, predict_race_time, race_predictions, training_paces, vdot_from_race

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

# Day slots relative to a Sunday long run (offset 6). "Q" = quality, "E" easy, "R" recovery, "L" long.
DAY_TEMPLATES = {
    3: {1: "Q1", 3: "E", 6: "L"},
    4: {1: "Q1", 3: "Q2", 5: "E", 6: "L"},
    5: {1: "Q1", 2: "E", 3: "Q2", 5: "E", 6: "L"},
    6: {0: "E", 1: "Q1", 2: "E", 3: "Q2", 5: "E", 6: "L"},
    7: {0: "E", 1: "Q1", 2: "E", 3: "Q2", 4: "R", 5: "E", 6: "L"},
}


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
    include_strength: bool = True
    name: str | None = None


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


def _volumes(req: PlanRequest, phases: list[str]) -> tuple[list[float], list[bool]]:
    peak = max(PEAK_VOLUME_KM[req.goal][req.level], req.current_weekly_km)
    min_start = {3: 12, 4: 16, 5: 20, 6: 25, 7: 30}[req.days_per_week]
    vol = max(req.current_weekly_km, min_start)
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


def _quality_sessions(goal: Goal, phase: str, wk_in_phase: int, n_q: int, level: Level, paces, weekly_km: float, recovery: bool) -> list[W.Workout]:
    """Pick 1-2 quality sessions following phase emphasis and Daniels' volume limits."""
    t_km = max(3.0, 0.10 * weekly_km)           # T <= 10% weekly
    i_km = max(2.4, min(10.0, 0.08 * weekly_km))  # I <= min(10 km, 8%)
    r_km = max(1.6, min(8.0, 0.05 * weekly_km))   # R <= min(8 km, 5%)
    t_min = min(30, max(12, round(t_km * paces.threshold.mid() / 60)))
    prog = wk_in_phase % 3  # progress within the phase

    def cruise():
        rep = 1000 if t_km < 6 else 1600 if t_km < 9 else 2000
        return W.cruise_intervals(paces, max(3, int(t_km * 1000 // rep)), rep)

    def vo2():
        rep = [800, 1000, 1200][prog]
        return W.vo2_intervals(paces, max(3, int(i_km * 1000 // rep)), rep)

    def reps():
        rep = 400 if r_km >= 3 else 200
        return W.repetitions(paces, max(6, min(12, int(r_km * 1000 // rep))), rep)

    if recovery:
        sessions = [W.easy_with_strides(paces, weekly_km * 0.15), W.progression_run(paces, max(5, weekly_km * 0.15))]
        return sessions[:n_q]

    if phase == "base":
        if level == "beginner" and wk_in_phase < 2:
            pool = [W.easy_with_strides(paces, weekly_km * 0.18), W.easy_with_strides(paces, weekly_km * 0.15, 4)]
        else:
            pool = [W.hills(paces, 6 + 2 * prog), W.progression_run(paces, max(5, weekly_km * 0.18)) if prog != 2 else W.tempo(paces, max(12, t_min - 8))]
            if goal in ("5k", "10k") and prog == 2:
                pool[0] = reps()
    elif phase == "build":
        if goal in ("5k", "10k"):
            pool = [vo2(), cruise() if prog != 1 else W.tempo(paces, t_min)]
        else:
            pool = [cruise() if prog != 1 else W.tempo(paces, t_min), vo2() if prog != 2 else reps()]
    elif phase == "peak":
        if goal == "5k":
            pool = [W.race_pace_intervals(paces, "five_k", [5, 6, 4][prog], 1000, 150, "5K"), cruise()]
        elif goal == "10k":
            pool = [W.race_pace_intervals(paces, "ten_k", [5, 4, 6][prog], [1600, 2000, 1000][prog], 90, "10K"), cruise()]
        elif goal == "half":
            pool = [W.race_pace_intervals(paces, "half", [3, 4, 3][prog], [3000, 3000, 4000][prog], 120, "medio maratón"), vo2()]
        elif goal == "marathon":
            pool = [cruise(), W.race_pace_intervals(paces, "marathon", 2, [5000, 6000, 7000][prog], 180, "maratón")]
        else:
            pool = [cruise(), vo2()]
    else:  # taper: keep intensity, cut volume (Bosquet 2007)
        zone, label = {"5k": ("five_k", "5K"), "10k": ("ten_k", "10K"), "half": ("half", "medio maratón"), "marathon": ("marathon", "maratón")}[goal]
        pool = [W.race_pace_intervals(paces, zone, 3, 1000, 90, label), W.easy_with_strides(paces, weekly_km * 0.15)]
    return pool[:n_q]


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


def generate_plan(req: PlanRequest) -> dict:
    if req.days_per_week not in DAY_TEMPLATES:
        raise ValueError("days_per_week must be 3..7")
    lo, hi = WEEKS_RANGE[req.goal]
    if req.race_date:
        first_monday = req.start_date - dt.timedelta(days=req.start_date.weekday())
        n_weeks = (req.race_date - first_monday).days // 7 + 1
    else:
        n_weeks = req.weeks or {"5k": 8, "10k": 10, "half": 12, "marathon": 16, "base": 8}[req.goal]
    warnings: list[str] = []
    if n_weeks < lo:
        warnings.append(f"Plan corto ({n_weeks} sem.). Recomendado al menos {lo} semanas para {req.goal}.")
    if n_weeks > hi and req.race_date:
        # Too far out: start the specific plan later; until then the athlete does base running.
        race_monday = req.race_date - dt.timedelta(days=req.race_date.weekday())
        req.start_date = race_monday - dt.timedelta(weeks=hi - 1)
        warnings.append(f"Carrera lejana: el plan empieza el {req.start_date.isoformat()} ({hi} semanas). Hasta entonces, plan 'base'.")
    n_weeks = max(min(n_weeks, hi), min(lo, n_weeks), 2)

    vdot0 = resolve_vdot(req)
    goal_vdot = None
    if req.goal_time_s and req.goal != "base":
        goal_vdot = vdot_from_race(RACE_DISTANCES_M[req.goal], req.goal_time_s)
        attainable = vdot0 + VDOT_GAIN_PER_WEEK[req.level] * n_weeks
        if goal_vdot > attainable + 0.5:
            pred = predict_race_time(attainable, RACE_DISTANCES_M[req.goal])
            warnings.append(f"Objetivo ambicioso: VDOT objetivo {goal_vdot:.1f} vs actual {vdot0:.1f}. "
                            f"Una predicción realista al final del plan es ~{fmt_time(pred)}. "
                            "Los ritmos se ajustarán según tus resultados reales.")
    if not (req.recent_race_distance or req.vdot):
        warnings.append("Sin marca reciente: ritmos estimados. Haz un test de 5K o 30' en la semana 1-2 para calibrar.")

    phases = _phase_split(n_weeks, req.goal)
    vols, recov = _volumes(req, phases)
    template = DAY_TEMPLATES[req.days_per_week]
    n_q_default = 1 if req.days_per_week == 3 or req.level == "beginner" and req.days_per_week <= 4 else 2
    cap_km, cap_min = LONG_RUN_CAP[req.goal]
    long_share = {3: 0.33, 4: 0.30, 5: 0.28, 6: 0.26, 7: 0.25}[req.days_per_week]
    if req.goal == "marathon":  # marathoners need 28-35 km long runs; allow a larger share (Pfitzinger/Hudson)
        long_share = max(long_share, 0.36)

    weeks: list[PlanWeek] = []
    phase_counter: dict[str, int] = {}
    prev_long = req.longest_recent_run_km
    for wi, (phase, vol, is_rec) in enumerate(zip(phases, vols, recov)):
        # Paces progress conservatively toward goal fitness; re-calibrate from real results.
        vdot = vdot0 + VDOT_GAIN_PER_WEEK[req.level] * wi * 0.5
        if goal_vdot:
            vdot = min(vdot, max(goal_vdot, vdot0))
        paces = training_paces(vdot)
        wk_in_phase = phase_counter.get(phase, 0)
        phase_counter[phase] = wk_in_phase + 1
        week = PlanWeek(wi + 1, phase, vol, vdot, is_recovery=is_rec)
        dates = _week_dates(req.start_date, wi)
        is_race_week = req.goal != "base" and wi == n_weeks - 1

        # Long run (time + distance capped, +<=2 km/week vs previous long)
        long_cap_by_time = cap_min * 60 / paces.long.mid()
        share = long_share + (0.06 if req.goal == "marathon" and phase == "peak" else 0)
        long_km = min(vol * share, cap_km, long_cap_by_time, prev_long + 2.0)
        if is_rec or phase == "taper":
            long_km = min(long_km, prev_long * 0.75 if is_rec else vol * long_share)
        long_km = max(long_km, 4)

        n_q = n_q_default
        quality = _quality_sessions(req.goal, phase, wk_in_phase, n_q, req.level, paces, vol, is_rec)
        # Low-frequency weeks (3 days): the share cap would leave an easy run longer than the long
        # run. Shift volume to the long run (still within the time/distance/+2 km caps), as
        # 3-day programs do, and cap easy runs at ~85 % of the long run.
        n_easy = sum(1 for k in template.values() if k in ("E", "R")) + (1 if n_q < 2 and "Q2" in template.values() else 0)
        q_km = sum(q.distance_km for q in quality[: 1 if n_q < 2 else 2])
        if n_easy and not is_rec and phase != "taper":
            ideal = (vol - q_km) / (1 + 0.85 * n_easy)
            long_km = max(long_km, min(ideal, cap_km, long_cap_by_time, prev_long + 2.0))
        if not is_rec:
            prev_long = max(prev_long, long_km)
        if req.goal == "marathon" and phase == "peak" and not is_rec and wk_in_phase % 2 == 1:
            lw = W.long_run(paces, long_km, fast_finish_km=round(min(16, long_km * 0.4)), fast_zone="marathon")
        elif req.goal == "half" and phase == "peak" and not is_rec and wk_in_phase % 2 == 1:
            lw = W.long_run(paces, long_km, fast_finish_km=round(min(8, long_km * 0.3)), fast_zone="half")
        else:
            lw = W.long_run(paces, long_km)
        if lw.intensity != "low" and len(quality) > 1:
            # Long run already carries race-pace work: keep only 2 hard days/week (80/20)
            quality[1] = W.easy_with_strides(paces, vol * 0.15)

        slots = dict(template)
        if n_q < 2:
            slots = {k: ("E" if v == "Q2" else v) for k, v in slots.items()}
        L = req.long_run_day
        assigned: dict[int, W.Workout] = {}
        easy_slots = []
        for off, kind in slots.items():
            day = (off - 6 + L) % 7
            if kind == "L":
                assigned[day] = lw
            elif kind == "Q1":
                assigned[day] = quality[0]
            elif kind == "Q2":
                assigned[day] = quality[1] if len(quality) > 1 else None
                if assigned[day] is None:
                    easy_slots.append(day)
            else:
                easy_slots.append((day, kind))

        used = sum(w.distance_km for w in assigned.values() if w)
        remaining = max(0.0, vol - used)
        easy_days = [d for d in easy_slots if isinstance(d, tuple)] + [(d, "E") for d in easy_slots if isinstance(d, int)]
        if easy_days:
            per = max(3.0, min(remaining / len(easy_days), long_km * 0.85))
            for day, kind in easy_days:
                assigned[day] = W.recovery_run(paces, per * 0.8) if kind == "R" else W.easy_run(paces, per)

        if is_race_week:
            race_day = (req.race_date or dates[L]).weekday()
            dist = RACE_DISTANCES_M[req.goal]
            zone = {"5k": "five_k", "10k": "ten_k", "half": "half", "marathon": "marathon"}[req.goal]
            assigned = {d: w for d, w in assigned.items() if d < race_day - 1 and w and w.type not in ("long",)}
            keep = sorted(assigned)[: max(0, req.days_per_week - 2)]  # race + shakeout fill the other run days
            assigned = {d: assigned[d] for d in keep}
            assigned[race_day - 1] = W.shakeout(paces) if race_day >= 1 else None
            assigned[race_day] = W.race(paces, req.goal, dist, zone)
            if not req.race_date:  # no target race: end with a time trial to re-calibrate VDOT
                assigned[race_day].title = f"🏁 Test {req.goal.upper()} (contrarreloj)"

        for day in sorted(d for d, w in assigned.items() if w):
            w = assigned[day]
            w.date = dates[day].isoformat()
            w.phase = phase
            week.workouts.append(w)

        if req.include_strength and phase != "taper" and not is_race_week:
            focus = "base" if phase == "base" else "build" if phase == "build" else "maintenance"
            q_days = [d for d, w in assigned.items() if w and w.intensity in ("moderate", "high") and w.type != "long"]
            for d in q_days[: (1 if phase == "peak" or is_rec else 2)]:
                s = W.strength_session(focus)
                s.date, s.phase = dates[d].isoformat(), phase
                week.workouts.append(s)
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
        "days_per_week": req.days_per_week,
        "vdot_start": round(vdot0, 1),
        "vdot_goal": round(goal_vdot, 1) if goal_vdot else None,
        "paces_start": training_paces(vdot0).as_dict(),
        "predictions_start": race_predictions(vdot0),
        "predictions_end": race_predictions(final_vdot),
        "warnings": warnings,
        "weeks": [w.to_dict() for w in weeks],
    }
