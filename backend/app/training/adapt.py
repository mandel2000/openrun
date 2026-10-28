"""Plan adaptation: readiness-based session modification and pace recalibration.

HRV-guided training (Vesterinen 2016; Javaloyes 2019; Düking 2021 meta-analysis) gives
similar or better gains than fixed plans with fewer non-responders: train hard when
readiness is normal, go easy when it is suppressed.
"""

from __future__ import annotations

from . import workouts as W
from .vdot import training_paces


def adjust_for_readiness(workout: dict, status: str, paces_vdot: float) -> tuple[dict, str]:
    """Return (possibly modified workout, explanation)."""
    w = W.Workout.from_dict(workout)
    paces = training_paces(paces_vdot)
    if w.sport != "running" or w.intensity == "low" or status in ("green", "unknown"):
        return workout, "Sin cambios: readiness normal o sesión ya suave."
    if status == "red":
        new = W.recovery_run(paces, min(6.0, max(3.0, w.distance_km * 0.5)))
        msg = "Readiness baja (HRV suprimida): sesión sustituida por regenerativo. Recupera la calidad otro día de la semana si te encuentras bien."
    else:  # amber: keep the stimulus, reduce dose ~25-30% (fewer reps), or move tempo to easy+strides
        new = W.clone(w)
        reduced = False
        for s in new.steps:
            if s.kind == "repeat" and s.repeat > 2:
                s.repeat = max(2, round(s.repeat * 0.7))
                reduced = True
        if not reduced:
            new = W.easy_with_strides(paces, w.distance_km * 0.8)
        new.title += " (reducida)"
        W.recompute(new)
        msg = "Readiness moderada: volumen de calidad reducido ~30% manteniendo intensidad."
    new.date, new.phase = w.date, w.phase
    return new.to_dict(), msg


def deload_workouts(workouts: list[dict], vdot: float, mode: str = "reduce") -> list[dict]:
    """'Not feeling 100%': reduce (quality -> easy, volume -30%) or rest (keep only short easy runs)."""
    paces = training_paces(vdot)
    out = []
    for wd in workouts:
        w = W.Workout.from_dict(wd)
        if w.sport != "running" or w.type == "race":
            out.append(wd)
            continue
        if mode == "rest":
            new = W.recovery_run(paces, min(5.0, w.distance_km * 0.5))
        elif w.intensity == "low":
            new = W.easy_run(paces, w.distance_km * 0.7) if w.type != "long" else W.long_run(paces, w.distance_km * 0.7)
        else:
            new = W.easy_with_strides(paces, w.distance_km * 0.7, 4)
        new.date, new.phase = w.date, w.phase
        out.append(new.to_dict())
    return out


def repace_workout(workout: dict, new_vdot: float) -> dict:
    """Recompute pace targets of a workout for a new VDOT (keeps structure)."""
    w = W.Workout.from_dict(workout)
    paces = training_paces(new_vdot)

    def fix(steps):
        for s in steps:
            if s.kind == "repeat":
                fix(s.steps)
            elif s.zone and s.pace_slow and s.pace_fast:
                pr = paces.get(s.zone)
                s.pace_slow, s.pace_fast = pr.slow, pr.fast

    fix(w.steps)
    W.recompute(w)
    return {**workout, **w.to_dict()}  # keep extra keys (race_id, extra, _orig...)
