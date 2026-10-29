"""Workout model + evidence-based session library.

A workout is a tree of steps. Each step has a duration (distance in m, time in s,
or open/lap-button) and an optional target (pace range from VDOT zones, or HR range).
The same structure is used by the UI, the AI coach and the Garmin exporter.

Session design follows Daniels' Running Formula volume limits per session:
- Threshold (T): <= 10% of weekly volume in one session; cruise reps of 5-15 min, ~1 min rest per 5 min.
- Interval (I, ~vVO2max): work bouts 3-5 min, <= min(10 km, 8% weekly), jog recovery ~ equal time.
- Repetition (R): 200-400 m, <= min(8 km, 5% weekly), full recovery (equal distance jog).
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Literal

from ..i18n import _
from .vdot import TrainingPaces, fmt_pace

StepKind = Literal["warmup", "run", "recovery", "rest", "cooldown", "repeat"]
DurationType = Literal["distance", "time", "open"]

# Low intensity zones count toward the "80" of 80/20 (Seiler 2010; Stöggl & Sperlich 2014).
LOW_ZONES = {"recovery", "easy", "long", None}


@dataclass
class Step:
    kind: StepKind
    duration_type: DurationType = "open"
    duration_value: float = 0.0  # meters or seconds
    zone: str | None = None  # VDOT zone name, e.g. "threshold"
    pace_slow: float | None = None  # s/km
    pace_fast: float | None = None
    hr_low: int | None = None
    hr_high: int | None = None
    repeat: int = 1
    steps: list[Step] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.kind != "repeat":
            d.pop("steps")
            d.pop("repeat")
        else:
            d["steps"] = [s.to_dict() for s in self.steps]
        return d

    @staticmethod
    def from_dict(d: dict) -> Step:
        d = dict(d)
        children = [Step.from_dict(s) for s in d.pop("steps", [])]
        known = {k: v for k, v in d.items() if k in Step.__dataclass_fields__}
        return Step(**known, steps=children)


@dataclass
class Workout:
    type: str
    title: str
    description: str
    steps: list[Step]
    intensity: Literal["rest", "low", "moderate", "high"] = "low"
    phase: str = ""
    date: str | None = None
    distance_km: float = 0.0
    duration_min: float = 0.0
    low_intensity_min: float = 0.0
    sport: Literal["running", "strength"] = "running"
    exercises: list[dict] | None = None  # strength sessions: [{name, sets, reps, rest_s, cue, load}]

    def to_dict(self) -> dict:
        extra = {"exercises": self.exercises} if self.exercises else {}
        return {**extra,
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "intensity": self.intensity,
            "phase": self.phase,
            "date": self.date,
            "distance_km": round(self.distance_km, 1),
            "duration_min": round(self.duration_min),
            "low_intensity_min": round(self.low_intensity_min),
            "sport": self.sport,
        }

    @staticmethod
    def from_dict(d: dict) -> Workout:
        w = Workout(
            type=d["type"],
            title=d["title"],
            description=d.get("description", ""),
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            intensity=d.get("intensity", "low"),
            phase=d.get("phase", ""),
            date=d.get("date"),
            sport=d.get("sport", "running"),
            exercises=d.get("exercises"),
        )
        recompute(w)
        return w


# ---------------------------------------------------------------- helpers


def _pace_step(kind: StepKind, paces: TrainingPaces, zone: str, *, meters: float | None = None, seconds: float | None = None, note: str = "") -> Step:
    pr = paces.get(zone)
    if meters is not None:
        return Step(kind, "distance", meters, zone, pr.slow, pr.fast, note=note)
    return Step(kind, "time", seconds or 0, zone, pr.slow, pr.fast, note=note)


def _iter_leaf(steps: list[Step], mult: int = 1):
    for s in steps:
        if s.kind == "repeat":
            yield from _iter_leaf(s.steps, mult * s.repeat)
        else:
            yield s, mult


def recompute(w: Workout) -> Workout:
    """Estimate distance/duration and low-intensity minutes from steps."""
    dist = dur = low = 0.0
    for s, mult in _iter_leaf(w.steps):
        pace = (s.pace_slow + s.pace_fast) / 2 if s.pace_slow and s.pace_fast else 390.0
        if s.duration_type == "distance":
            d_m, t_s = s.duration_value, s.duration_value / 1000 * pace
        elif s.duration_type == "time":
            t_s = s.duration_value
            d_m = 0.0 if s.kind == "rest" else t_s / pace * 1000
        else:
            d_m, t_s = 0.0, 0.0
        dist += d_m * mult
        dur += t_s * mult
        if s.zone in LOW_ZONES or s.kind in ("rest", "recovery", "warmup", "cooldown"):
            low += t_s * mult
    w.distance_km, w.duration_min, w.low_intensity_min = dist / 1000, dur / 60, low / 60
    return w


def _wu(paces, km=2.0):
    return _pace_step("warmup", paces, "easy", meters=km * 1000, note=_("Easy warm-up + dynamic mobility"))


def _cd(paces, km=1.5):
    return _pace_step("cooldown", paces, "easy", meters=km * 1000, note=_("Easy cool-down"))


def _mk(type_, title, desc, steps, intensity, paces=None) -> Workout:
    return recompute(Workout(type_, title, desc, steps, intensity))


def _round_km(x: float, step: float = 0.5) -> float:
    return max(step, round(x / step) * step)


# ---------------------------------------------------------------- library


def easy_run(paces: TrainingPaces, km: float) -> Workout:
    km = _round_km(km)
    return _mk("easy", _("Easy run {km} km", km=f"{km:g}"),
               _("Aerobic base: mitochondrial density and capillarisation at a low recovery cost. "
                 "It should feel conversational (RPE 3-4/10). ~80% of the weekly volume goes here (Seiler 2010)."),
               [_pace_step("run", paces, "easy", meters=km * 1000)], "low")


def recovery_run(paces: TrainingPaces, km: float) -> Workout:
    km = _round_km(km)
    return _mk("recovery", _("Recovery run {km} km", km=f"{km:g}"),
               _("Very easy, to add volume without fatigue. If you feel tired, rest instead."),
               [_pace_step("run", paces, "recovery", meters=km * 1000)], "low")


def easy_with_strides(paces: TrainingPaces, km: float, n: int = 6) -> Workout:
    km = _round_km(max(km - 0.8, 2))
    return _mk("strides", _("Easy {km} km + {n} strides", km=f"{km:g}", n=n),
               _("Strides (~20 s at R pace, full recovery) improve running economy and neuromuscular "
                 "mechanics without a meaningful metabolic load."),
               [_pace_step("run", paces, "easy", meters=km * 1000),
                Step("repeat", repeat=n, steps=[_pace_step("run", paces, "repetition", seconds=20, note=_("Relaxed and fast, not a sprint")),
                                                Step("recovery", "time", 60, note=_("Walk / very easy jog"))])], "low")


def hills(paces: TrainingPaces, reps: int = 8) -> Workout:
    return _mk("hills", _("Hills {reps}×60 s", reps=reps),
               _("Short hills at ~5K effort: specific strength, power and economy with less impact "
                 "than on the flat (Barnes et al. 2013). Jog down as recovery."),
               [_wu(paces, 2.5),
                Step("repeat", repeat=reps, steps=[Step("run", "time", 60, "interval", note=_("4-8% hill, hard, RPE 8")),
                                                   Step("recovery", "time", 90, note=_("Jog down"))]),
                _cd(paces, 2)], "moderate")


def progression_run(paces: TrainingPaces, km: float) -> Workout:
    km = _round_km(km, 1)
    a, b = _round_km(km * 0.6), _round_km(km * 0.25)
    c = max(_round_km(km - a - b), 1)
    return _mk("progression", _("Progression run {km} km", km=f"{km:g}"),
               _("Finishes at threshold pace: a gentle threshold stimulus, ideal in the base phase."),
               [_pace_step("run", paces, "easy", meters=a * 1000),
                _pace_step("run", paces, "marathon", meters=b * 1000),
                _pace_step("run", paces, "threshold", meters=c * 1000)], "moderate")


def tempo(paces: TrainingPaces, minutes: int) -> Workout:
    return _mk("tempo", _("Tempo {min}' at threshold", min=minutes),
               _("Continuous run at T pace (~1-hour race pace, 'comfortably hard'): raises the lactate threshold. "
                 "Daniels caps continuous T at ~20-30 min."),
               [_wu(paces), _pace_step("run", paces, "threshold", seconds=minutes * 60), _cd(paces)], "moderate")


def cruise_intervals(paces: TrainingPaces, reps: int, rep_m: int) -> Workout:
    rest = max(60, round(rep_m / 1000 * paces.threshold.mid() / 5 / 60) * 60)  # ~1' per 5' of work
    return _mk("threshold", _("Threshold {reps}×{km} km", reps=reps, km=f"{rep_m / 1000:g}"),
               _("Cruise intervals at T pace with short rests (≈1' per 5' of work). "
                 "More total time at threshold than a continuous tempo, with less fatigue (Daniels)."),
               [_wu(paces), Step("repeat", repeat=reps, steps=[_pace_step("run", paces, "threshold", meters=rep_m),
                                                             Step("recovery", "time", rest, note=_("Easy jog"))]),
                _cd(paces)], "moderate")


def vo2_intervals(paces: TrainingPaces, reps: int, rep_m: int) -> Workout:
    work_s = rep_m / 1000 * paces.interval.mid()
    return _mk("intervals", f"VO2max {reps}×{rep_m:g} m",
               _("Intervals at I pace (~vVO2max, 3-5 min per rep) with jog recoveries of similar "
                 "duration: maximises time near VO2max (Billat 2001; Midgley 2006)."),
               [_wu(paces, 2.5), Step("repeat", repeat=reps, steps=[_pace_step("run", paces, "interval", meters=rep_m),
                                                                  Step("recovery", "time", round(work_s * 0.8 / 10) * 10, note=_("Jog"))]),
                _cd(paces, 2)], "high")


def repetitions(paces: TrainingPaces, reps: int, rep_m: int) -> Workout:
    return _mk("reps", _("R reps {reps}×{m} m", reps=reps, m=f"{rep_m:g}"),
               _("Fast repetitions at R pace with full recovery: speed and running economy."),
               [_wu(paces, 2.5), Step("repeat", repeat=reps, steps=[_pace_step("run", paces, "repetition", meters=rep_m),
                                                                  Step("recovery", "distance", rep_m, "recovery", paces.recovery.slow, paces.recovery.fast, note=_("Jog"))]),
                _cd(paces, 2)], "high")


def race_pace_intervals(paces: TrainingPaces, zone: str, reps: int, rep_m: int, rest_s: int, label: str) -> Workout:
    return _mk("race_pace", _("{reps}×{km} km at {label} pace", reps=reps, km=f"{rep_m / 1000:g}", label=label),
               _("Specific work at your {label} goal pace: metabolic and economy specificity, "
                 "and confidence at race pace.", label=label),
               [_wu(paces), Step("repeat", repeat=reps, steps=[_pace_step("run", paces, zone, meters=rep_m),
                                                             Step("recovery", "time", rest_s, note=_("Easy jog"))]),
                _cd(paces)], "high" if zone in ("five_k", "ten_k") else "moderate")


def long_run(paces: TrainingPaces, km: float, fast_finish_km: float = 0, fast_zone: str = "marathon") -> Workout:
    km = _round_km(km)
    if fast_finish_km <= 0:
        return _mk("long", _("Long run {km} km", km=f"{km:g}"),
                   _("Aerobic endurance, fat use, musculoskeletal adaptation. Steady easy pace; "
                     "practise drinks/gels if it lasts >75'."),
                   [_pace_step("run", paces, "long", meters=km * 1000)], "low")
    base = _round_km(km - fast_finish_km)
    label = _("marathon") if fast_zone == "marathon" else _("half marathon")
    return _mk("long", _("Long {km} km with {fast} km at {label} pace", km=f"{km:g}", fast=f"{fast_finish_km:g}", label=label),
               _("Long run with a final block at goal pace: simulates race fatigue and trains "
                 "economy at race pace (specificity approach, Canova/Pfitzinger)."),
               [_pace_step("run", paces, "long", meters=base * 1000),
                _pace_step("run", paces, fast_zone, meters=fast_finish_km * 1000)], "moderate")


def shakeout(paces: TrainingPaces) -> Workout:
    return _mk("shakeout", _("Pre-race shakeout"),
               _("20' very easy + 4 strides. Keeps your legs feeling fresh."),
               [_pace_step("run", paces, "easy", seconds=20 * 60),
                Step("repeat", repeat=4, steps=[_pace_step("run", paces, "repetition", seconds=15), Step("recovery", "time", 60)])], "low")


def race(paces: TrainingPaces, goal: str, distance_m: float, zone: str) -> Workout:
    names = {"5k": "5K", "10k": "10K", "half": _("Half marathon"), "marathon": _("Marathon")}
    return _mk("race", "🏁 " + _("Race: {name}", name=names.get(goal, goal)),
               _("Race day. Start controlled for the first km and run a negative split if you can."),
               [_pace_step("run", paces, zone, meters=distance_m)], "high")


def strength_session(focus: Literal["base", "build", "maintenance"]) -> Workout:
    """Strength for runners (structured exercises: see training/strength.py for the evidence)."""
    from .strength import describe, session

    sess = session(focus)
    w = Workout("strength", sess["title"], sess["goal"] + " " + _("Do it on the same day as the quality session, after running "
                "(hard days hard, easy days easy).") + f" {describe(sess)}.",
                [Step("run", "time", sess["minutes"] * 60, None, note=_("Strength session"))], "moderate", sport="strength",
                exercises=sess["exercises"])
    w.duration_min, w.distance_km, w.low_intensity_min = sess["minutes"], 0, 0
    return w


def describe_steps(steps: list[Step], indent: str = "") -> str:
    """Human-readable step list (used by AI coach + UI fallback)."""
    lines = []
    for s in steps:
        if s.kind == "repeat":
            lines.append(f"{indent}{s.repeat}× (")
            lines.append(describe_steps(s.steps, indent + "  "))
            lines.append(f"{indent})")
            continue
        dur = (f"{s.duration_value / 1000:g} km" if s.duration_type == "distance"
               else f"{s.duration_value / 60:g} min" if s.duration_type == "time" else "open")
        tgt = f" @ {fmt_pace(s.pace_slow)}-{fmt_pace(s.pace_fast)}/km ({s.zone})" if s.pace_slow and s.pace_fast else ""
        if s.hr_low and s.hr_high:
            tgt += f" HR {s.hr_low}-{s.hr_high}"
        lines.append(f"{indent}- {s.kind}: {dur}{tgt}{' — ' + s.note if s.note else ''}")
    return "\n".join(lines)


def clone(w: Workout) -> Workout:
    return copy.deepcopy(w)
