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
    return _pace_step("warmup", paces, "easy", meters=km * 1000, note="Calentamiento suave + movilidad dinámica")


def _cd(paces, km=1.5):
    return _pace_step("cooldown", paces, "easy", meters=km * 1000, note="Vuelta a la calma suave")


def _mk(type_, title, desc, steps, intensity, paces=None) -> Workout:
    return recompute(Workout(type_, title, desc, steps, intensity))


def _round_km(x: float, step: float = 0.5) -> float:
    return max(step, round(x / step) * step)


# ---------------------------------------------------------------- library


def easy_run(paces: TrainingPaces, km: float) -> Workout:
    km = _round_km(km)
    return _mk("easy", f"Rodaje suave {km:g} km",
               "Base aeróbica: densidad mitocondrial y capilarización con bajo coste de recuperación. "
               "Debe sentirse conversacional (RPE 3-4/10). ~80% del volumen semanal va aquí (Seiler 2010).",
               [_pace_step("run", paces, "easy", meters=km * 1000)], "low")


def recovery_run(paces: TrainingPaces, km: float) -> Workout:
    km = _round_km(km)
    return _mk("recovery", f"Regenerativo {km:g} km",
               "Muy suave para sumar volumen sin fatiga. Si te notas cansado, mejor descansa.",
               [_pace_step("run", paces, "recovery", meters=km * 1000)], "low")


def easy_with_strides(paces: TrainingPaces, km: float, n: int = 6) -> Workout:
    km = _round_km(max(km - 0.8, 2))
    return _mk("strides", f"Suave {km:g} km + {n} progresivos",
               "Los progresivos (~20 s a ritmo R, recuperación completa) mejoran la economía y la mecánica "
               "neuromuscular sin carga metabólica relevante.",
               [_pace_step("run", paces, "easy", meters=km * 1000),
                Step("repeat", repeat=n, steps=[_pace_step("run", paces, "repetition", seconds=20, note="Relajado, rápido, no sprint"),
                                                Step("recovery", "time", 60, note="Caminar/trote muy suave")])], "low")


def hills(paces: TrainingPaces, reps: int = 8) -> Workout:
    return _mk("hills", f"Cuestas {reps}×60 s",
               "Cuestas cortas al ~5K de esfuerzo: fuerza específica, potencia y economía con menor impacto "
               "que en llano (Barnes et al. 2013). Bajar trotando como recuperación.",
               [_wu(paces, 2.5),
                Step("repeat", repeat=reps, steps=[Step("run", "time", 60, "interval", note="Cuesta 4-8% fuerte, RPE 8"),
                                                   Step("recovery", "time", 90, note="Bajar trotando")]),
                _cd(paces, 2)], "moderate")


def progression_run(paces: TrainingPaces, km: float) -> Workout:
    km = _round_km(km, 1)
    a, b = _round_km(km * 0.6), _round_km(km * 0.25)
    c = max(_round_km(km - a - b), 1)
    return _mk("progression", f"Progresivo {km:g} km",
               "Termina a ritmo umbral: estímulo de umbral suave idóneo en fase base.",
               [_pace_step("run", paces, "easy", meters=a * 1000),
                _pace_step("run", paces, "marathon", meters=b * 1000),
                _pace_step("run", paces, "threshold", meters=c * 1000)], "moderate")


def tempo(paces: TrainingPaces, minutes: int) -> Workout:
    return _mk("tempo", f"Tempo {minutes}' a umbral",
               "Carrera continua a ritmo T (~1 h de carrera, 'cómodamente duro'): eleva el umbral de lactato. "
               "Daniels limita T continuo a ~20-30 min.",
               [_wu(paces), _pace_step("run", paces, "threshold", seconds=minutes * 60), _cd(paces)], "moderate")


def cruise_intervals(paces: TrainingPaces, reps: int, rep_m: int) -> Workout:
    rest = max(60, round(rep_m / 1000 * paces.threshold.mid() / 5 / 60) * 60)  # ~1' per 5' of work
    return _mk("threshold", f"Umbral {reps}×{rep_m / 1000:g} km",
               "Intervalos de crucero a ritmo T con descanso corto (≈1' por cada 5' de trabajo). "
               "Permite más tiempo total a umbral que el tempo continuo con menos fatiga (Daniels).",
               [_wu(paces), Step("repeat", repeat=reps, steps=[_pace_step("run", paces, "threshold", meters=rep_m),
                                                             Step("recovery", "time", rest, note="Trote suave")]),
                _cd(paces)], "moderate")


def vo2_intervals(paces: TrainingPaces, reps: int, rep_m: int) -> Workout:
    work_s = rep_m / 1000 * paces.interval.mid()
    return _mk("intervals", f"VO2max {reps}×{rep_m:g} m",
               "Intervalos a ritmo I (~vVO2max, 3-5 min por repetición) con recuperación trotando de igual "
               "duración: maximiza el tiempo cerca del VO2max (Billat 2001; Midgley 2006).",
               [_wu(paces, 2.5), Step("repeat", repeat=reps, steps=[_pace_step("run", paces, "interval", meters=rep_m),
                                                                  Step("recovery", "time", round(work_s * 0.8 / 10) * 10, note="Trote")]),
                _cd(paces, 2)], "high")


def repetitions(paces: TrainingPaces, reps: int, rep_m: int) -> Workout:
    return _mk("reps", f"Series R {reps}×{rep_m:g} m",
               "Repeticiones rápidas a ritmo R con recuperación completa: velocidad y economía de carrera.",
               [_wu(paces, 2.5), Step("repeat", repeat=reps, steps=[_pace_step("run", paces, "repetition", meters=rep_m),
                                                                  Step("recovery", "distance", rep_m, "recovery", paces.recovery.slow, paces.recovery.fast, note="Trote")]),
                _cd(paces, 2)], "high")


def race_pace_intervals(paces: TrainingPaces, zone: str, reps: int, rep_m: int, rest_s: int, label: str) -> Workout:
    return _mk("race_pace", f"{reps}×{rep_m / 1000:g} km a ritmo {label}",
               f"Trabajo específico al ritmo objetivo de {label}: especificidad metabólica y de economía, "
               "y confianza en el ritmo de carrera.",
               [_wu(paces), Step("repeat", repeat=reps, steps=[_pace_step("run", paces, zone, meters=rep_m),
                                                             Step("recovery", "time", rest_s, note="Trote suave")]),
                _cd(paces)], "high" if zone in ("five_k", "ten_k") else "moderate")


def long_run(paces: TrainingPaces, km: float, fast_finish_km: float = 0, fast_zone: str = "marathon") -> Workout:
    km = _round_km(km)
    if fast_finish_km <= 0:
        return _mk("long", f"Tirada larga {km:g} km",
                   "Resistencia aeróbica, uso de grasas, adaptación musculoesquelética. Ritmo suave constante; "
                   "practica hidratación/geles si dura >75'.",
                   [_pace_step("run", paces, "long", meters=km * 1000)], "low")
    base = _round_km(km - fast_finish_km)
    label = "maratón" if fast_zone == "marathon" else "medio maratón"
    return _mk("long", f"Larga {km:g} km con {fast_finish_km:g} km a ritmo {label}",
               "Tirada larga con bloque final a ritmo objetivo: simula la fatiga de carrera y entrena "
               "la economía al ritmo de competición (enfoque de especificidad, Canova/Pfitzinger).",
               [_pace_step("run", paces, "long", meters=base * 1000),
                _pace_step("run", paces, fast_zone, meters=fast_finish_km * 1000)], "moderate")


def shakeout(paces: TrainingPaces) -> Workout:
    return _mk("shakeout", "Activación pre-carrera",
               "20' muy suaves + 4 progresivos. Mantiene la sensación de piernas frescas.",
               [_pace_step("run", paces, "easy", seconds=20 * 60),
                Step("repeat", repeat=4, steps=[_pace_step("run", paces, "repetition", seconds=15), Step("recovery", "time", 60)])], "low")


def race(paces: TrainingPaces, goal: str, distance_m: float, zone: str) -> Workout:
    names = {"5k": "5K", "10k": "10K", "half": "Medio maratón", "marathon": "Maratón"}
    return _mk("race", f"🏁 Carrera: {names.get(goal, goal)}",
               "Día de carrera. Sal controlado los primeros km y negativa si puedes.",
               [_pace_step("run", paces, zone, meters=distance_m)], "high")


def strength_session(focus: Literal["base", "build", "maintenance"]) -> Workout:
    """Strength for runners (structured exercises: see training/strength.py for the evidence)."""
    from .strength import describe, session

    sess = session(focus)
    w = Workout("strength", sess["title"], f"{sess['goal']} Hazla el mismo día que la sesión de calidad, después de correr "
                f"(días duros duros, suaves suaves). {describe(sess)}.",
                [Step("run", "time", sess["minutes"] * 60, None, note="Sesión de fuerza")], "moderate", sport="strength",
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
               else f"{s.duration_value / 60:g} min" if s.duration_type == "time" else "libre")
        tgt = f" @ {fmt_pace(s.pace_slow)}-{fmt_pace(s.pace_fast)}/km ({s.zone})" if s.pace_slow and s.pace_fast else ""
        if s.hr_low and s.hr_high:
            tgt += f" FC {s.hr_low}-{s.hr_high}"
        lines.append(f"{indent}- {s.kind}: {dur}{tgt}{' — ' + s.note if s.note else ''}")
    return "\n".join(lines)


def clone(w: Workout) -> Workout:
    return copy.deepcopy(w)
