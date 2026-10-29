"""Strength & mobility for runners: structured sessions instead of a text blob.

Evidence:
- Heavy (≥80 % 1RM) and explosive/plyometric training improves running economy 2-8 % and
  time-trial performance without hurting VO2max (Blagrove et al. 2018; Balsalobre-Fernández
  et al. 2016 meta-analysis; Støren et al. 2008).
- Calf-soleus capacity: the soleus takes ~6-8× body weight per stride; loaded calf raises with
  bent knee target it (Dorn et al. 2012; Achilles/calf injury prevention).
- Hip abductor / glute strength and single-leg control relate to running-injury risk (Willy &
  Davis 2011; patellofemoral pain). Copenhagen adduction lowers groin injuries (Harøy 2019).
- Same day as quality runs, after them (hard days hard), ≥6 h apart if possible; drop to
  maintenance volume in the peak and none in race week (Beattie 2014; periodisation).
- Static stretching before running does not prevent injury and can blunt power; a dynamic
  warm-up does help (Behm 2016). Post-run mobility is for comfort/range, short and gentle.
"""

from __future__ import annotations

import copy

from ..i18n import N_, _


def ex(name: str, sets: int, reps: str, rest_s: int, cue: str, load: str = "") -> dict:
    return {"name": name, "sets": sets, "reps": reps, "rest_s": rest_s, "cue": cue, "load": load}


# Texts are English and translated when a session is handed out (localized()).
SESSIONS: dict[str, dict] = {
    "base": {
        "title": N_("General strength"),
        "goal": N_("Base strength and single-leg control: tendons and joints ready to handle more km."),
        "minutes": 35,
        "exercises": [
            ex(N_("Goblet squat"), 3, "10-12", 75, N_("Chest up, knees track over the toes, down to thighs parallel."), N_("RPE 7: 3 reps in reserve")),
            ex(N_("Romanian deadlift"), 3, "10", 75, N_("Hips back with a neutral spine, dumbbells close to the legs; feel the hamstrings.")),
            ex(N_("Reverse lunge"), 3, N_("8 per leg"), 60, N_("Long step back, front knee stable without caving in.")),
            ex(N_("Single-leg glute bridge"), 3, N_("12 per leg"), 45, N_("Push through the heel, pelvis level, squeeze the glute at the top for 1 s.")),
            ex(N_("Standing calf raise (straight knee)"), 3, "15", 45, N_("Up in 1 s, down in 3 s, full range on a step.")),
            ex(N_("Seated calf raise (bent knee)"), 3, "15", 45, N_("Soleus: weight on the knees, slow and full range.")),
            ex(N_("Side plank"), 3, N_("30 s per side"), 30, N_("Body in line, hips high, don't sink into the shoulder.")),
        ],
    },
    "build": {
        "title": N_("Max strength + plyometrics"),
        "goal": N_("Heavy strength and tendon stiffness to improve running economy (2-8%)."),
        "minutes": 40,
        "exercises": [
            ex(N_("Box jumps"), 3, "5", 90, N_("Maximum intent, land softly and step down. Quality over fatigue."), N_("First, while fresh")),
            ex(N_("Pogos (ankle hops)"), 3, "20", 60, N_("Knees almost straight, quick bounce on the forefoot, short ground contact.")),
            ex(N_("Squat or trap-bar deadlift"), 4, "5", 150, N_("Heavy but clean: perfect technique on every rep."), N_("RPE 8 (2 in reserve)")),
            ex(N_("Loaded step-up"), 3, N_("6 per leg"), 90, N_("Knee-height box, drive only with the top leg.")),
            ex(N_("Loaded soleus raise (seated)"), 3, "10-12", 60, N_("Heavy load, 3 s down.")),
            ex(N_("Copenhagen plank (adductors)"), 2, N_("6-8 per side"), 45, N_("Short version (knee supported) the first time.")),
        ],
    },
    "maintenance": {
        "title": N_("Strength maintenance"),
        "goal": N_("Keep what you gained with little volume: it must not leave you tired for the next quality session."),
        "minutes": 25,
        "exercises": [
            ex(N_("Pogos"), 2, "15", 60, N_("Quick, springy bounce.")),
            ex(N_("Heavy trap-bar or goblet squat"), 2, "5", 120, N_("Heavy, few reps, far from failure."), "RPE 7-8"),
            ex(N_("Romanian deadlift"), 2, "6", 90, N_("Controlled.")),
            ex(N_("Loaded soleus raise"), 2, "12", 45, N_("Slow on the way down.")),
            ex(N_("Front plank"), 2, "40 s", 30, N_("Glutes on, don't arch the lower back.")),
        ],
    },
}

MOBILITY = {
    "title": N_("Post-run mobility"),
    "goal": N_("10 easy minutes after running to restore range of motion. No bouncing, no pain."),
    "minutes": 10,
    "exercises": [
        ex(N_("Hip flexor stretch (kneeling)"), 1, N_("45 s per side"), 0, N_("Tuck the pelvis and push the hip forward.")),
        ex(N_("Calf and soleus against a wall"), 1, N_("30 s + 30 s per leg"), 0, N_("First with the knee straight, then bent.")),
        ex(N_("Hamstring stretch, leg raised"), 1, N_("45 s per leg"), 0, N_("Straight back, lean from the hips.")),
        ex(N_("Figure 4 (glute/piriformis)"), 1, N_("45 s per side"), 0, N_("Lying down, ankle over the opposite knee.")),
        ex(N_("Quadruped thoracic rotation"), 1, N_("8 per side"), 0, N_("Hand behind the head, open the elbow to the ceiling and follow it with your eyes.")),
        ex(N_("Diaphragmatic breathing, lying down"), 1, "1 min", 0, N_("Breathe in for 4 s, out for 6 s: lowers heart rate and kick-starts recovery.")),
    ],
}

WARMUP = {
    "title": N_("Dynamic warm-up"),
    "goal": N_("5-8 minutes before intervals or races. No static stretching here."),
    "minutes": 7,
    "exercises": [
        ex(N_("Front-to-back leg swings"), 1, N_("10 per leg"), 0, N_("Hold on to a wall, gradually bigger.")),
        ex(N_("Side leg swings"), 1, N_("10 per leg"), 0, N_("Loose hips.")),
        ex(N_("Lunge with rotation"), 1, N_("5 per side"), 0, N_("Turn the torso towards the front leg.")),
        ex(N_("Low skips"), 2, "20 m", 0, N_("Quick cadence, short contact.")),
        ex(N_("Butt kicks"), 2, "20 m", 0, N_("Relaxed.")),
        ex(N_("Strides"), 3, "80 m", 45, N_("From easy to fast (not a sprint), walk back.")),
    ],
}


def localized(block: dict) -> dict:
    """Copy of a session/routine with its texts in the current user's language."""
    out = copy.deepcopy(block)
    out["title"], out["goal"] = _(out["title"]), _(out["goal"])
    for e in out["exercises"]:
        for k in ("name", "reps", "cue", "load"):
            if e[k]:
                e[k] = _(e[k])
    return out


def session(focus: str) -> dict:
    return localized(SESSIONS.get(focus) or SESSIONS["base"])


def focus_for_title(title: str) -> str:
    """Stored strength workouts only keep their title (in the language they were created in)."""
    t = (title or "").lower()
    if "máxima" in t or "pliometr" in t or "max strength" in t or "plyometric" in t:
        return "build"
    return "maintenance" if "manten" in t or "maintenance" in t else "base"


def describe(sess: dict) -> str:
    return " · ".join(f"{e['name']} {e['sets']}×{e['reps']}" for e in sess["exercises"])
