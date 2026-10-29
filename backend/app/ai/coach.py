"""AI running coach: Claude + tools over the athlete's real data.

The model never invents pace numbers: workouts are created from structure + VDOT zone
names, and the server derives exact pace targets from the athlete's current VDOT.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from typing import Any

import anthropic
from sqlmodel import Session, select

from .. import services as S
from ..db import ChatMessage
from ..i18n import _, language_name
from ..training.vdot import RACE_DISTANCES_M, parse_time, race_predictions, training_paces, vdot_from_race

MODEL = os.getenv("OPENRUN_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("OPENRUN_EFFORT", "medium")
MAX_TOOL_ROUNDS = 12

SYSTEM = """You are OpenRun's running coach. Direct and friendly.

Principles (mandatory, evidence-based):
- ~80/20 intensity distribution (Seiler): at most 2 quality sessions per week + an easy long run.
- Paces ALWAYS from the athlete's VDOT (Daniels). Use the zone names: recovery, easy, long, marathon, half,
  threshold, ten_k, five_k, interval, repetition. Never write made-up paces: the server computes them.
- Per-session limits (Daniels): threshold <= 10% of weekly volume; I intervals (3-5 min) <= min(10 km, 8%);
  R repetitions <= min(8 km, 5%). Warm-up >= 10-15' before quality.
- Volume progression <= ~10%/week with a recovery week every 3-4; ACWR below ~1.3.
- Readiness: if HRV (7-day average) is below baseline ±0.5 SD, or resting HR +5 bpm, or poor sleep,
  reduce the quality or swap it for easy running (HRV-guided training, Javaloyes 2019).
- Taper: -40-60% volume over 1-3 weeks keeping intensity (Bosquet 2007).
- Strength 2x/week (heavy + plyometrics) improves economy (Blagrove 2018).
- Races during the build-up: A = goal (plan periodised towards it), B = tune-up (2-3 day mini-taper and
  ~1 easy day per 3 km raced), C = training (no taper, counts as a quality session). At most one B every
  3-4 weeks and never in the 3 weeks before a half/marathon A race.
- Predictions: use get_race_predictions; explain they are estimates and the consensus combines several models.
- With pain, injury or medical symptoms, recommend stopping and seeing a health professional.

How to work:
- Before recommending, check the data with the tools (profile, plan, recent activities, readiness, load).
- When the athlete asks for a workout, create it with create_workout (structure + zones) and briefly explain why
  (the physiological adaptation sought and the evidence). Offer to send it to Garmin with push_to_garmin.
- To change an existing workout use create_workout with replace_id.
- Be concrete: numbers, dates, paces (read paces from the tools). Keep answers short.
- Only running workouts can be sent to Garmin (not strength). Don't promise actions your tools can't do.
- NEVER use tools that change data (generate_plan, create_workout, move_workout, delete_workout, add_extra_run,
  not_feeling_100, adapt_today_to_readiness, push_to_garmin, add_race, delete_race, update_athlete_profile, calculate_vdot with save)
  unless the athlete explicitly asked for it in their last message. If you think it's a good idea, propose it and ask first.
- Efficiency: the CURRENT SUMMARY already has the plan, upcoming workouts, readiness, load, activities, records, predictions and
  races (its keys are in Spanish). Don't call tools to read that. If you need several tools, request them all at once in one answer.
- Always answer in {language}, without words from other languages. Workout titles and notes come from the app in
  the athlete's language.
Today's date: {today}."""

SNAPSHOT_INTRO = ("\n\nCURRENT ATHLETE SUMMARY (real OpenRun data, already read for you). Use it directly; "
                  "only call tools if you need more detail (a workout's steps, a longer history) or to make changes:\n")

STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["warmup", "run", "recovery", "rest", "cooldown", "repeat"]},
        "duration_type": {"type": "string", "enum": ["distance", "time", "open"], "description": "distance in metres, time in seconds"},
        "duration_value": {"type": "number"},
        "zone": {"type": "string", "enum": ["recovery", "easy", "long", "marathon", "half", "threshold", "ten_k", "five_k", "interval", "repetition"]},
        "repeat": {"type": "integer", "description": "only for kind=repeat"},
        "steps": {"type": "array", "items": {"type": "object"}, "description": "only for kind=repeat: child steps in the same format"},
        "note": {"type": "string"},
    },
    "required": ["kind"],
}

TOOLS: list[dict[str, Any]] = [
    {"name": "get_athlete_profile", "description": "Athlete profile: VDOT, paces per zone, predictions, HR zones.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "update_athlete_profile", "description": "Updates athlete data (age, sex, max HR, resting HR, LTHR, km/week).",
     "input_schema": {"type": "object", "properties": {"age": {"type": "integer"}, "sex": {"type": "string", "enum": ["male", "female"]},
                                                         "max_hr": {"type": "integer"}, "rest_hr": {"type": "integer"}, "lthr": {"type": "integer"},
                                                         "weekly_km": {"type": "number"}}}},
    {"name": "get_plan_overview", "description": "Active plan: goal, phases, weekly volume, % low intensity, warnings (no per-workout detail).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_workouts", "description": "Planned workouts between two dates (YYYY-MM-DD) with id, status and steps.",
     "input_schema": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}, "required": ["start", "end"]}},
    {"name": "get_recent_activities", "description": "Recent real activities: distance, pace, HR, TRIMP, training effect.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "default": 21}}}},
    {"name": "get_readiness", "description": "Today's readiness: 0-100 score and its parts (HRV, sleep, resting HR, load, feel check-in), the proposal for today's workout and the last 14 days of wellness.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_training_load", "description": "Load: CTL (fitness 42d), ATL (fatigue 7d), TSB (form) and ACWR, last 28 days.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "calculate_vdot", "description": "VDOT, training paces and predictions from a race result.",
     "input_schema": {"type": "object", "properties": {"distance": {"type": "string", "enum": list(RACE_DISTANCES_M)},
                                                         "time": {"type": "string", "description": "h:mm:ss or mm:ss"},
                                                         "save": {"type": "boolean", "description": "true to update the athlete's VDOT and recompute the paces of future workouts"}},
                      "required": ["distance", "time"]}},
    {"name": "create_workout", "description": "Creates (or replaces with replace_id) a structured workout. Paces are computed from the VDOT by 'zone'.",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string"}, "title": {"type": "string"},
         "type": {"type": "string", "enum": ["easy", "recovery", "long", "strides", "hills", "progression", "tempo", "threshold", "intervals", "reps", "race_pace", "fartlek", "test"]},
         "description": {"type": "string", "description": "Physiological goal and rationale"},
         "intensity": {"type": "string", "enum": ["low", "moderate", "high"]},
         "steps": {"type": "array", "items": STEP_SCHEMA},
         "replace_id": {"type": "integer"}},
         "required": ["date", "title", "type", "steps", "description", "intensity"]}},
    {"name": "delete_workout", "description": "Deletes a planned workout by id.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "move_workout", "description": "Moves a workout to another date. With swap=true, whatever was on that day moves to the original date (swap). Returns warnings if two hard days end up in a row.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}, "date": {"type": "string"}, "swap": {"type": "boolean"}}, "required": ["id", "date"]}},
    {"name": "add_extra_run", "description": "Adds an optional easy run to a week (outside the base plan). Returns warnings if volume rises > 10% or it comes before a key session.",
     "input_schema": {"type": "object", "properties": {"date": {"type": "string"}, "km": {"type": "number"}}, "required": ["date"]}},
    {"name": "get_personal_records", "description": "Personal records (1K, mile, 5K, 10K, half, marathon): all time, last year, 6 months and 30 days, from best efforts.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_race_predictions", "description": "Race time predictions (VDOT from 90-day best efforts, Riegel, Garmin, HR) and consensus; monthly VDOT trend; suggests recalibrating if it differs from the plan's VDOT.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_races", "description": "Races the athlete has entered (priority A goal / B tune-up / C training).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_race_strategy", "description": "Strategy for an entered race: km-by-km target pace adjusted for the course elevation (GPX or approximate profile), flat vs course prediction, heat forecast and gel/carb plan.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}, "mode": {"type": "string", "enum": ["conservative", "realistic", "ambitious"]}}, "required": ["id"]}},
    {"name": "search_race_calendar", "description": "Searches upcoming races in the Orycron Sport calendar (Salamanca area, Spain). With external_id returns the details (place, time, distances).",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "external_id": {"type": "string"}}}},
    {"name": "add_race", "description": "Enters a race and fits it into the plan: B = 3-day mini-taper + recovery; C = as a quality session; A = goal (suggests regenerating the plan). Ask the athlete to confirm first.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
         "distance_m": {"type": "number"}, "priority": {"type": "string", "enum": ["A", "B", "C"]},
         "location": {"type": "string"}, "url": {"type": "string"}, "external_id": {"type": "string"}},
         "required": ["name", "date", "distance_m", "priority"]}},
    {"name": "delete_race", "description": "Removes a race and undoes its plan adjustments.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "generate_plan", "description": "Generates a new plan (replaces the active one). Ask the athlete to confirm before using it.",
     "input_schema": {"type": "object", "properties": {
         "goal": {"type": "string", "enum": ["5k", "10k", "half", "marathon", "base"]},
         "start_date": {"type": "string"}, "race_date": {"type": "string"}, "weeks": {"type": "integer"},
         "days_per_week": {"type": "integer", "minimum": 3, "maximum": 7}, "long_run_day": {"type": "integer", "description": "0=lunes..6=domingo"},
         "current_weekly_km": {"type": "number"}, "longest_recent_run_km": {"type": "number"},
         "level": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
         "recent_race_distance": {"type": "string", "enum": list(RACE_DISTANCES_M)}, "recent_race_time": {"type": "string"},
         "goal_time": {"type": "string"}, "include_strength": {"type": "boolean"}},
         "required": ["goal", "days_per_week", "current_weekly_km", "level"]}},
    {"name": "adapt_today_to_readiness", "description": "Adjusts today's workout to readiness (HRV/HR/sleep).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "not_feeling_100", "description": "The athlete isn't 100%: reduces (or active rest) the next N days.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 14},
                                                         "mode": {"type": "string", "enum": ["reduce", "rest"]}}, "required": ["days"]}},
    {"name": "get_missed_sessions", "description": "Workouts from the last few days that weren't done and, for key sessions, the proposed slot to make them up this week.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "reschedule_missed", "description": "Reschedules a missed key session into its proposed slot (accept=true) or marks it as skipped (accept=false).",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}, "accept": {"type": "boolean"}}, "required": ["id", "accept"]}},
    {"name": "report_break", "description": "The athlete has been off for N days (illness, injury, travel): closes the missed workouts, adjusts paces if needed and eases the return. Ask to confirm first.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 120},
                                                         "reason": {"type": "string", "enum": ["illness", "injury", "travel", "other"]}}, "required": ["days"]}},
    {"name": "push_to_garmin", "description": "Sends workouts (ids) to the Garmin Connect calendar to sync with the watch.",
     "input_schema": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "integer"}}}, "required": ["ids"]}},
]


def _strip_heavy(ws: list[dict]) -> list[dict]:
    from ..training.workouts import Step, describe_steps
    return [{k: v for k, v in w.items() if k not in ("steps", "description")} | {"steps_readable": describe_steps([Step.from_dict(s) for s in w.get("steps", [])])} for w in ws]


def run_tool(s: Session, name: str, args: dict) -> Any:
    today = dt.date.today()
    if name == "get_athlete_profile":
        return S.athlete_profile(s)
    if name == "update_athlete_profile":
        return S.update_athlete(s, **args)
    if name == "get_plan_overview":
        p = S.plan_overview(s)
        if not p:
            return {"plan": None}
        return {**{k: v for k, v in p.items() if k != "weeks"},
                "weeks": [{k: v for k, v in w.items() if k != "workouts"} | {"n_workouts": len(w["workouts"])} for w in p["weeks"]]}
    if name == "get_workouts":
        return _strip_heavy(S.list_workouts(s, args["start"], args["end"]))
    if name == "get_recent_activities":
        return S.recent_activities(s, args.get("days", 21))
    if name == "get_readiness":
        return {**S.readiness_view(s), "last_14_days": S.wellness_rows(s, 14)}
    if name == "get_training_load":
        tl = S.training_load(s, 28)
        return {"series": tl["series"], "fitness_estimate_from_hr": S.fitness_estimate(s)}
    if name == "calculate_vdot":
        v = vdot_from_race(RACE_DISTANCES_M[args["distance"]], parse_time(args["time"]))
        out = {"vdot": round(v, 1), "paces": training_paces(v).as_dict(), "predictions": race_predictions(v)}
        if args.get("save"):
            out["recalibration"] = S.recalibrate_paces(s, v, f"{args['distance']} {args['time']}")
        return out
    if name == "create_workout":
        return S.save_custom_workout(s, args["date"], args["title"], args["type"], args["steps"],
                                     args.get("description", ""), args.get("intensity", "moderate"), args.get("replace_id"))
    if name == "delete_workout":
        S.delete_workout(s, args["id"])
        return {"ok": True}
    if name == "add_extra_run":
        return S.add_extra_run(s, args["date"], args.get("km"))
    if name == "get_personal_records":
        return S.personal_records(s)
    if name == "get_race_predictions":
        return S.race_time_predictions(s)
    if name == "list_races":
        return S.list_races(s)
    if name == "get_race_strategy":
        st = S.race_strategy(s, args["id"], args.get("mode"))
        from ..training.vdot import fmt_pace, fmt_time
        return {"carrera": st["race"]["name"], "fecha": st["race"]["date"], "salida": st["start_time"], "modo": st["mode"],
                "objetivo": fmt_time(st["target_s"]), "media": fmt_pace(st["avg_pace_s"]), "mitad": fmt_time(st["half_s"]) if st["half_s"] else None,
                "recorrido": {k: st["course"][k] for k in ("name", "approx", "flat", "gain_m", "loss_m", "factor")},
                "prediccion": {k: fmt_time(v) for k, v in st["prediction"]["modes"].items()}, "tiempo": st["weather"],
                "km": [f"{k['km']}: {fmt_pace(k['pace_s'])} {k['terrain']}{' — ' + k['note'] if k['note'] else ''}" for k in st["kms"]],
                "comida": st["fuel"]}
    if name == "search_race_calendar":
        from ..integrations import orycron
        if args.get("external_id"):
            return orycron.event(args["external_id"])
        q = (args.get("query") or "").lower()
        return [i for i in orycron.upcoming() if not q or q in i["name"].lower()]
    if name == "add_race":
        extra = {k: args[k] for k in ("location", "url", "external_id") if args.get(k)}
        return S.add_race(s, args["name"], args["date"], args.get("distance_m"), args.get("priority", "B"),
                          source="orycron" if str(args.get("external_id", "")).startswith("orycron") else "manual", **extra)
    if name == "delete_race":
        S.delete_race(s, args["id"])
        return {"ok": True}
    if name == "move_workout":
        return S.move_workout(s, args["id"], args["date"], bool(args.get("swap")))
    if name == "generate_plan":
        p = S.create_plan(s, args)
        return {k: v for k, v in p.items() if k != "weeks"} | {"n_weeks": len(p["weeks"])}
    if name == "adapt_today_to_readiness":
        return S.adapt_today(s, today.isoformat())
    if name == "get_missed_sessions":
        return S.replan_check(s)
    if name == "reschedule_missed":
        return S.replan_apply(s, int(args["id"]), bool(args["accept"]))
    if name == "report_break":
        return S.report_break(s, int(args["days"]), args.get("reason", "other"))
    if name == "not_feeling_100":
        return _strip_heavy(S.not_feeling_well(s, args["days"], args.get("mode", "reduce")))
    if name == "push_to_garmin":
        return S.push_to_garmin(s, args["ids"])
    raise ValueError(f"herramienta desconocida: {name}")


def _history(s: Session) -> list[dict]:
    return [{"role": m.role, "content": m.content}
            for m in s.exec(select(ChatMessage).where(ChatMessage.role != "oa").order_by(ChatMessage.id)).all()]


def _save(s: Session, role: str, content: Any) -> None:
    s.add(ChatMessage(role=role, content=content))
    s.commit()


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


# OpenAI-compatible providers (free or local options). Base URL / key env / default model.
OPENAI_COMPAT = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-flash-latest"),
    # build.nvidia.com: free for NVIDIA Developer Program members (~40 req/min, trial/evaluation terms)
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", "minimaxai/minimax-m3.1-flash"),
    "ollama": ("http://localhost:11434/v1", None, "qwen3:8b"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openai/gpt-oss-120b:free"),
    "openai": (None, "OPENAI_API_KEY", "gpt-5-mini"),
}


def provider() -> str:
    return os.getenv("OPENRUN_PROVIDER", "anthropic").lower()


def provider_info() -> dict:
    p = provider()
    if p == "anthropic":
        return {"provider": p, "model": MODEL, "configured": bool(os.getenv("ANTHROPIC_API_KEY"))}
    base, key_env, default = OPENAI_COMPAT.get(p, (None, None, None))
    return {"provider": p, "model": os.getenv("OPENRUN_MODEL", default),
            "configured": p == "ollama" or bool(key_env and os.getenv(key_env)) or bool(os.getenv("OPENRUN_API_KEY"))}


def chat(s: Session, user_text: str) -> dict:
    if provider() != "anthropic":
        return _chat_openai_compat(s, user_text)
    return _chat_anthropic(s, user_text)


def _openai_client():
    import openai
    p = provider()
    if p not in OPENAI_COMPAT:
        raise ValueError(f"OPENRUN_PROVIDER desconocido: {p}")
    base, key_env, _model = OPENAI_COMPAT[p]
    key = os.getenv("OPENRUN_API_KEY") or (os.getenv(key_env) if key_env else None) or "ollama"
    # Free tiers rate-limit hard (NVIDIA ~40 req/min): let the SDK back off and retry 429s
    return openai.OpenAI(base_url=os.getenv("OPENRUN_BASE_URL", base), api_key=key, max_retries=4, timeout=120)


def context_snapshot(s: Session) -> str:
    """Compact JSON of what the coach usually needs, so small models answer in 1 round instead of 6."""
    today = dt.date.today()
    snap: dict[str, Any] = {"hoy": today.isoformat()}

    def part(key: str, fn) -> None:
        try:
            v = fn()
            if v not in (None, [], {}):
                snap[key] = v
        except Exception:  # noqa: BLE001 - a missing piece must not break the chat
            pass

    def athlete():
        a = S.athlete_profile(s)
        return {"vdot": a.get("vdot"), "fc_max": a.get("max_hr"), "fc_reposo": a.get("rest_hr"), "lthr": a.get("lthr"),
                "ritmos_por_zona": {z: f"{p['slow_fmt']}-{p['fast_fmt']}" for z, p in (a.get("paces") or {}).items() if isinstance(p, dict)}}

    def plan():
        p = S.plan_overview(s)
        if not p:
            return None
        cur = next((w for w in p["weeks"] if w["start"] <= today.isoformat() <= w["end"]), None)
        return {"nombre": p["name"], "objetivo": p["goal"], "inicio": p["start_date"], "carrera": p.get("race_date"), "semanas": len(p["weeks"]),
                "semana_actual": {"n": cur["index"], "fase": cur["phase"], "km_plan": cur["planned_km"], "km_hechos": cur["done_km"]} if cur else None}

    def next_days():
        ws = S.list_workouts(s, today.isoformat(), (today + dt.timedelta(days=7)).isoformat())
        if not ws:  # before the plan starts: show its first sessions
            p = S.plan_overview(s)
            ws = p["weeks"][0]["workouts"] if p and p["weeks"] else []
        return [{"id": w["id"], "fecha": w["date"], "titulo": w["title"], "km": w.get("distance_km"), "deporte": w.get("sport"),
                 "estado": w["status"], "en_garmin": bool(w.get("garmin_workout_id"))} for w in ws[:10]]

    def readiness():
        r = S.readiness_today(s)
        return {k: r.get(k) for k in ("status", "reasons", "hrv_7d", "swc_low", "swc_high")}

    def load():
        series = S.training_load(s, 28)["series"]
        last = series[-1] if series else {}
        return {k: last.get(k) for k in ("ctl", "atl", "tsb", "acwr")}

    def activities():
        out = []
        for a in S.recent_activities(s, 14)[:8]:
            out.append({"fecha": a["date"], "nombre": (a.get("name") or "")[:40], "deporte": a.get("sport"), "km": round((a.get("distance_m") or 0) / 1000, 1),
                        "ritmo": f"{int(a['pace_s_km'] // 60)}:{int(a['pace_s_km'] % 60):02d}" if a.get("pace_s_km") else None,
                        "fc": a.get("avg_hr"), "analisis": (a.get("analysis") or {}).get("verdict")})
        return out

    def records():
        r = S.personal_records(s)["records"]
        return {w: {k: f"{v['time']} ({v['date']})" for k, v in r[w].items() if k in ("1k", "5k", "10k", "half", "marathon")} for w in ("all", "1y")}

    def predictions():
        p = S.race_time_predictions(s)
        return {"consenso": {k: v["time"] for k, v in p["consensus"].items()}, "vdot_consenso": p.get("consensus_vdot"),
                "modelos": {m["label"]: {"fuente": m.get("source"), **{k: v["time"] for k, v in m["times"].items()}} for m in p["models"].values()},
                "tendencia_vdot_mensual": p.get("trend"), "sugerir_recalibrar_a": p.get("suggest_vdot")}

    def races():
        return [{"id": r["id"], "nombre": r["name"], "fecha": r["date"], "km": round(r["distance_m"] / 1000, 1) if r.get("distance_m") else None,
                 "prioridad": r["priority"]} for r in S.list_races(s) if r["days_to_go"] >= 0]

    for key, fn in (("atleta", athlete), ("plan", plan), ("proximos_entrenos", next_days), ("readiness", readiness),
                    ("carga", load), ("actividades_14d", activities), ("records", records), ("predicciones", predictions),
                    ("carreras", races)):
        part(key, fn)
    return json.dumps(snap, ensure_ascii=False, default=str)


def system_prompt(s: Session) -> str:
    return SYSTEM.format(today=dt.date.today().strftime("%A %d/%m/%Y"), language=language_name()) + SNAPSHOT_INTRO + context_snapshot(s)


# Small free models sometimes leak tokens from other scripts (Hangul, CJK, Cyrillic...) into Spanish text.
_FOREIGN = re.compile(r"[\u0400-\u04FF\u0590-\u05FF\u0600-\u06FF\u0E00-\u0E7F\u1100-\u11FF\u3040-\u30FF\u3130-\u318F\u4E00-\u9FFF\uAC00-\uD7AF]+")


def sanitize(text: str) -> str:
    return _FOREIGN.sub("", text)


def _dump_call(c) -> dict:
    # Keep provider extras (e.g. Gemini's extra_content.google.thought_signature, required on replay)
    try:
        d = c.model_dump(exclude_none=True)
        json.dumps(d)
        return d
    except Exception:  # noqa: BLE001
        return {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}


FALLBACK_MODELS = {"nvidia": ["openai/gpt-oss-20b"]}
# Reasoning models (MiniMax, gpt-oss) think silently before answering; "low" cuts time-to-first-word
# on the free NVIDIA tier from ~15-70 s to ~5 s. OPENRUN_REASONING_EFFORT="" disables the parameter.
REASONING_DEFAULT = {"nvidia": "low"}
STREAMING = {"nvidia", "ollama", "groq", "openrouter", "openai"}  # Gemini needs non-streamed thought signatures


def _models() -> list[str]:
    env = [m.strip() for m in os.getenv("OPENRUN_MODEL_FALLBACKS", "").split(",") if m.strip()]
    first = provider_info()["model"]
    return [first] + [m for m in (env or FALLBACK_MODELS.get(provider(), [])) if m != first]


def _completion(client, model: str, messages: list[dict], tools: list[dict], stream: bool):
    """Yields ("text", delta) / ("thinking", None) events and finally ("message", {"content", "tool_calls"})."""
    import openai

    kw = {"model": model, "messages": messages, "tools": tools, "temperature": 0.3}
    effort = os.getenv("OPENRUN_REASONING_EFFORT", REASONING_DEFAULT.get(provider(), ""))
    if effort:
        kw["reasoning_effort"] = effort
    if not stream:
        msg = client.chat.completions.create(**kw).choices[0].message
        if msg.content:
            yield "text", sanitize(msg.content)
        yield "message", {"content": sanitize(msg.content or ""), "tool_calls": [_dump_call(c) for c in (msg.tool_calls or [])]}
        return
    content, calls = [], {}
    try:
        chunks = client.chat.completions.create(stream=True, **kw)
    except openai.BadRequestError:
        if "reasoning_effort" not in kw:
            raise
        kw.pop("reasoning_effort")  # model doesn't accept the parameter
        chunks = client.chat.completions.create(stream=True, **kw)
    last_think = 0.0
    for chunk in chunks:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        extra = getattr(delta, "model_extra", None) or {}
        if (extra.get("reasoning_content") or extra.get("reasoning")) and time.time() - last_think > 2:
            last_think = time.time()
            yield "thinking", None
        if delta.content:
            clean = sanitize(delta.content)
            content.append(clean)
            if clean:
                yield "text", clean
        for tc in delta.tool_calls or []:
            slot = calls.setdefault(tc.index, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}})
            if tc.id:
                slot["id"] = tc.id
            if tc.function and tc.function.name:
                slot["function"]["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                slot["function"]["arguments"] += tc.function.arguments
    tool_calls = [c | {"id": c["id"] or f"call_{i}"} for i, c in sorted(calls.items())]
    yield "message", {"content": "".join(content), "tool_calls": tool_calls}


def complete(system: str, prompt: str, max_tokens: int = 900) -> str | None:
    """One-shot text generation without tools (weekly review, notifications). None if no provider works."""
    p = provider()
    if p == "anthropic":
        if not os.getenv("ANTHROPIC_API_KEY"):
            return None
        try:
            resp = _client().messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                             messages=[{"role": "user", "content": prompt}])
            return "".join(b.text for b in resp.content if b.type == "text").strip() or None
        except Exception:  # noqa: BLE001
            return None
    if not provider_info()["configured"]:
        return None
    client = _openai_client()
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    for model in _models():
        try:
            kw = {"model": model, "messages": msgs, "temperature": 0.3, "max_tokens": max_tokens}
            effort = os.getenv("OPENRUN_REASONING_EFFORT", REASONING_DEFAULT.get(p, ""))
            if effort:
                kw["reasoning_effort"] = effort
            text = client.chat.completions.create(**kw).choices[0].message.content
            if text and text.strip():
                return sanitize(text).strip()
        except Exception:  # noqa: BLE001 - try the next model
            continue
    return None


def chat_events(s: Session, user_text: str):
    """One user turn as a stream of events: {"type": "text"|"tool"|"status"|"done", ...}.
    Same tool loop for any OpenAI-compatible provider; falls back to the next model on errors."""
    import openai
    _save(s, "oa", [{"role": "user", "content": user_text}])
    client = _openai_client()
    models = _models()
    system = system_prompt(s)
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
             for t in TOOLS]
    tool_log: list[dict] = []
    reply: list[str] = []
    stream = provider() in STREAMING
    for _round in range(MAX_TOOL_ROUNDS):
        history = [m.content[0] for m in s.exec(select(ChatMessage).where(ChatMessage.role == "oa").order_by(ChatMessage.id)).all()]
        msg = None
        while models:
            try:
                round_text = []
                for kind, val in _completion(client, models[0], [{"role": "system", "content": system}, *history], tools, stream):
                    if kind == "text":
                        round_text.append(val)
                        yield {"type": "text", "delta": val}
                    elif kind == "thinking":
                        yield {"type": "status", "text": _("Thinking")}
                    else:
                        msg = val
                break
            except openai.AuthenticationError:
                yield {"type": "done", "reply": _("The API key for {provider} is missing or invalid.", provider=provider()), "tools": tool_log, "error": True}
                return
            except openai.APIConnectionError as e:
                if isinstance(e, openai.APITimeoutError) and len(models) > 1:
                    pass
                elif provider() == "ollama":
                    yield {"type": "done", "reply": _("Cannot connect to Ollama (is it running?)."), "tools": tool_log, "error": True}
                    return
                err = _("not responding")
            except (openai.RateLimitError, openai.NotFoundError, openai.InternalServerError) as e:
                err = f"error {getattr(e, 'status_code', '')}".strip()
            except openai.APIStatusError as e:
                yield {"type": "done", "reply": _("Provider error ({code}): {msg}", code=e.status_code, msg=e.message), "tools": tool_log, "error": True}
                return
            failed = models.pop(0)
            if round_text:
                yield {"type": "text", "delta": "\n\n"}
            if not models:
                yield {"type": "done", "reply": _("The AI model is not responding right now (free tier overloaded). Try again later."), "tools": tool_log, "error": True}
                return
            yield {"type": "status", "text": _("{failed} {err}; trying {model}", failed=failed, err=err, model=models[0])}
        calls = msg["tool_calls"]
        if msg["content"]:
            reply.append(msg["content"])
        _save(s, "oa", [{"role": "assistant", "content": msg["content"], **({"tool_calls": calls} if calls else {})}])
        if not calls:  # the last round is the answer; earlier text was preamble before tool calls
            yield {"type": "done", "reply": msg["content"] or "\n\n".join(reply), "tools": tool_log}
            return
        for c in calls:
            name = c["function"]["name"]
            yield {"type": "tool", "name": name}
            try:
                out = run_tool(s, name, json.loads(c["function"]["arguments"] or "{}"))
                content = json.dumps(out, default=str, ensure_ascii=False)[:60000]
                tool_log.append({"tool": name, "ok": True})
            except Exception as e:  # noqa: BLE001
                content = f"Error: {e}"
                tool_log.append({"tool": name, "ok": False, "error": str(e)})
            _save(s, "oa", [{"role": "tool", "tool_call_id": c["id"], "content": content}])
        if calls:
            system = system_prompt(s)  # tools may have changed the plan: refresh the summary
    yield {"type": "done", "reply": _("I reached the step limit for this request."), "tools": tool_log}


def _chat_openai_compat(s: Session, user_text: str) -> dict:
    out: dict = {}
    for ev in chat_events(s, user_text):
        if ev["type"] == "done":
            out = {k: v for k, v in ev.items() if k != "type"}
    return out


def _chat_anthropic(s: Session, user_text: str) -> dict:
    """Run one user turn through the manual tool loop. History is append-only (thinking blocks preserved)."""
    _save(s, "user", [{"type": "text", "text": user_text}])
    client = _client()
    system = system_prompt(s)
    tool_log: list[dict] = []
    for _round in range(MAX_TOOL_ROUNDS):
        try:
            resp = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=[{"type": "text", "text": system}],
                tools=TOOLS,
                messages=_history(s),
                thinking={"type": "adaptive"},
                output_config={"effort": EFFORT},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            return {"reply": _("The Anthropic API key (ANTHROPIC_API_KEY) is missing or invalid."), "tools": tool_log, "error": True}
        except anthropic.RateLimitError:
            return {"reply": _("API rate limit reached; try again in a moment."), "tools": tool_log, "error": True}
        except anthropic.APIStatusError as e:
            return {"reply": _("API error ({code}): {msg}", code=e.status_code, msg=e.message), "tools": tool_log, "error": True}
        except anthropic.APIConnectionError:
            return {"reply": _("Cannot connect to the Anthropic API."), "tools": tool_log, "error": True}

        content = [b.model_dump(exclude_none=True) for b in resp.content]
        _save(s, "assistant", content)

        if resp.stop_reason == "refusal":
            return {"reply": _("I can't help with that request."), "tools": tool_log}
        if resp.stop_reason != "tool_use":
            text = "\n".join(b.text for b in resp.content if b.type == "text")
            return {"reply": text, "tools": tool_log}

        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                out = run_tool(s, b.name, b.input if isinstance(b.input, dict) else json.loads(b.input))
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out, default=str, ensure_ascii=False)[:60000]})
                tool_log.append({"tool": b.name, "ok": True})
            except Exception as e:  # noqa: BLE001 - surface tool errors to the model
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"Error: {e}", "is_error": True})
                tool_log.append({"tool": b.name, "ok": False, "error": str(e)})
        _save(s, "user", results)
    return {"reply": _("I reached the step limit for this request."), "tools": tool_log}


def visible_history(s: Session) -> list[dict]:
    out = []
    oa = provider() != "anthropic"
    for m in s.exec(select(ChatMessage).order_by(ChatMessage.id)).all():
        if (m.role == "oa") != oa:
            continue
        if m.role == "oa":
            msg = m.content[0]
            if msg["role"] in ("user", "assistant") and (msg.get("content") or "").strip():
                out.append({"role": msg["role"], "text": msg["content"], "tools": []})
            elif msg.get("tool_calls"):
                out.append({"role": "tool", "text": "", "tools": [c["function"]["name"] for c in msg["tool_calls"]]})
            continue
        texts = [b.get("text", "") for b in m.content if isinstance(b, dict) and b.get("type") == "text"]
        tools = [b.get("name") for b in m.content if isinstance(b, dict) and b.get("type") == "tool_use"]
        if texts and any(t.strip() for t in texts):
            out.append({"role": m.role, "text": "\n".join(texts), "tools": tools})
        elif tools:
            out.append({"role": "tool", "text": "", "tools": tools})
    return out


def reset(s: Session) -> None:
    for m in s.exec(select(ChatMessage)).all():
        s.delete(m)
    s.commit()
