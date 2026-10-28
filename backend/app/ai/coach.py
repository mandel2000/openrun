"""AI running coach: Claude + tools over the athlete's real data.

The model never invents pace numbers: workouts are created from structure + VDOT zone
names, and the server derives exact pace targets from the athlete's current VDOT.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

import anthropic
from sqlmodel import Session, select

from .. import services as S
from ..db import ChatMessage
from ..training.vdot import RACE_DISTANCES_M, parse_time, race_predictions, training_paces, vdot_from_race

MODEL = os.getenv("OPENRUN_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("OPENRUN_EFFORT", "medium")
MAX_TOOL_ROUNDS = 12

SYSTEM = """Eres el entrenador de running de OpenRun. Hablas en español, directo y cercano.

Principios (obligatorios, basados en evidencia):
- Distribución de intensidad ~80/20 (Seiler): como máximo 2 sesiones de calidad por semana + tirada larga suave.
- Ritmos SIEMPRE desde el VDOT del atleta (Daniels). Usa los nombres de zona: recovery, easy, long, marathon, half,
  threshold, ten_k, five_k, interval, repetition. Nunca escribas ritmos inventados: el servidor los calcula.
- Límites por sesión (Daniels): umbral <= 10% del volumen semanal; intervalos I (3-5 min) <= min(10 km, 8%);
  repeticiones R <= min(8 km, 5%). Calentamiento >= 10-15' antes de calidad.
- Progresión de volumen <= ~10%/semana con semana de descarga cada 3-4; ACWR por debajo de ~1.3.
- Readiness: si la HRV (media 7 días) está por debajo de la base ±0.5 DE, o FC reposo +5 ppm, o mal sueño,
  reduce o cambia la calidad por suave (entrenamiento guiado por HRV, Javaloyes 2019).
- Taper: -40-60% volumen en 1-3 semanas manteniendo intensidad (Bosquet 2007).
- Fuerza 2x/semana (pesado + pliometría) mejora la economía (Blagrove 2018).
- Carreras durante la preparación: A = objetivo (plan periodizado hacia ella), B = preparatoria (mini-taper 2-3 días y
  ~1 día suave por cada 3 km de carrera), C = entreno (sin taper, cuenta como sesión de calidad). Máximo una B cada
  3-4 semanas y nunca en las 3 semanas previas a una A de medio/maratón.
- Predicciones: usa get_race_predictions; explica que son estimaciones y que el consenso combina varios modelos.
- Si hay dolor, lesión o síntomas médicos, recomienda parar y consultar a un profesional sanitario.

Forma de trabajar:
- Antes de recomendar, consulta los datos con las herramientas (perfil, plan, actividades recientes, readiness, carga).
- Cuando el atleta pida un entreno, créalo con create_workout (estructura + zonas) y explica brevemente el porqué
  (adaptación fisiológica buscada y evidencia). Ofrece enviarlo a Garmin con push_to_garmin.
- Para cambiar un entreno existente usa create_workout con replace_id.
- Sé concreto: números, fechas, ritmos (lee los ritmos de las herramientas). Respuestas breves.
Fecha de hoy: {today}."""

STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["warmup", "run", "recovery", "rest", "cooldown", "repeat"]},
        "duration_type": {"type": "string", "enum": ["distance", "time", "open"], "description": "distance en metros, time en segundos"},
        "duration_value": {"type": "number"},
        "zone": {"type": "string", "enum": ["recovery", "easy", "long", "marathon", "half", "threshold", "ten_k", "five_k", "interval", "repetition"]},
        "repeat": {"type": "integer", "description": "solo para kind=repeat"},
        "steps": {"type": "array", "items": {"type": "object"}, "description": "solo para kind=repeat: pasos hijos con el mismo formato"},
        "note": {"type": "string"},
    },
    "required": ["kind"],
}

TOOLS: list[dict[str, Any]] = [
    {"name": "get_athlete_profile", "description": "Perfil del atleta: VDOT, ritmos por zona, predicciones, zonas de FC.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "update_athlete_profile", "description": "Actualiza datos del atleta (edad, sexo, FC máx, FC reposo, LTHR, km/semana).",
     "input_schema": {"type": "object", "properties": {"age": {"type": "integer"}, "sex": {"type": "string", "enum": ["male", "female"]},
                                                         "max_hr": {"type": "integer"}, "rest_hr": {"type": "integer"}, "lthr": {"type": "integer"},
                                                         "weekly_km": {"type": "number"}}}},
    {"name": "get_plan_overview", "description": "Plan activo: objetivo, fases, volumen semanal, % baja intensidad, warnings (sin detalle de cada entreno).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_workouts", "description": "Entrenos planificados entre dos fechas (YYYY-MM-DD) con id, estado y pasos.",
     "input_schema": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}, "required": ["start", "end"]}},
    {"name": "get_recent_activities", "description": "Actividades reales recientes (Garmin): distancia, ritmo, FC, TRIMP, training effect.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "default": 21}}}},
    {"name": "get_readiness", "description": "Readiness de hoy (HRV vs línea base, FC reposo, sueño) y últimos 14 días de bienestar.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_training_load", "description": "Carga: CTL (fitness 42d), ATL (fatiga 7d), TSB (forma) y ACWR, últimos 28 días.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "calculate_vdot", "description": "VDOT, ritmos de entrenamiento y predicciones a partir de una marca.",
     "input_schema": {"type": "object", "properties": {"distance": {"type": "string", "enum": list(RACE_DISTANCES_M)},
                                                         "time": {"type": "string", "description": "h:mm:ss o mm:ss"},
                                                         "save": {"type": "boolean", "description": "true para actualizar el VDOT del atleta y re-calcular ritmos de entrenos futuros"}},
                      "required": ["distance", "time"]}},
    {"name": "create_workout", "description": "Crea (o reemplaza con replace_id) un entreno estructurado. Los ritmos se calculan del VDOT según 'zone'.",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string"}, "title": {"type": "string"},
         "type": {"type": "string", "enum": ["easy", "recovery", "long", "strides", "hills", "progression", "tempo", "threshold", "intervals", "reps", "race_pace", "fartlek", "test"]},
         "description": {"type": "string", "description": "Objetivo fisiológico y justificación"},
         "intensity": {"type": "string", "enum": ["low", "moderate", "high"]},
         "steps": {"type": "array", "items": STEP_SCHEMA},
         "replace_id": {"type": "integer"}},
         "required": ["date", "title", "type", "steps", "description", "intensity"]}},
    {"name": "delete_workout", "description": "Elimina un entreno planificado por id.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "move_workout", "description": "Mueve un entreno a otra fecha.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}, "date": {"type": "string"}}, "required": ["id", "date"]}},
    {"name": "add_extra_run", "description": "Añade un rodaje suave opcional a una semana (fuera del plan base). Devuelve avisos si sube el volumen > 10 % o precede a una sesión clave.",
     "input_schema": {"type": "object", "properties": {"date": {"type": "string"}, "km": {"type": "number"}}, "required": ["date"]}},
    {"name": "get_personal_records", "description": "Récords personales (1K, milla, 5K, 10K, media, maratón) históricos, último año, 6 meses y 30 días, desde los mejores tramos de Garmin.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_race_predictions", "description": "Predicciones de tiempo en carrera (VDOT de mejores esfuerzos 90 d, Riegel, Garmin, FC) y consenso; tendencia mensual de VDOT; sugiere recalibrar si difiere del VDOT del plan.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_races", "description": "Carreras apuntadas por el atleta (prioridad A objetivo / B preparatoria / C entreno).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "search_race_calendar", "description": "Busca próximas carreras en el calendario de Orycron Sport (Salamanca y alrededores). Con external_id devuelve la ficha (lugar, hora, distancias).",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "external_id": {"type": "string"}}}},
    {"name": "add_race", "description": "Apunta una carrera y la integra en el plan: B = mini-taper 3 días + recuperación; C = como entreno de calidad; A = objetivo (sugiere regenerar plan). Pide confirmación al atleta antes.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
         "distance_m": {"type": "number"}, "priority": {"type": "string", "enum": ["A", "B", "C"]},
         "location": {"type": "string"}, "url": {"type": "string"}, "external_id": {"type": "string"}},
         "required": ["name", "date", "distance_m", "priority"]}},
    {"name": "delete_race", "description": "Quita una carrera y deshace sus ajustes en el plan.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "generate_plan", "description": "Genera un plan nuevo (reemplaza el activo). Pide confirmación al atleta antes de usarla.",
     "input_schema": {"type": "object", "properties": {
         "goal": {"type": "string", "enum": ["5k", "10k", "half", "marathon", "base"]},
         "start_date": {"type": "string"}, "race_date": {"type": "string"}, "weeks": {"type": "integer"},
         "days_per_week": {"type": "integer", "minimum": 3, "maximum": 7}, "long_run_day": {"type": "integer", "description": "0=lunes..6=domingo"},
         "current_weekly_km": {"type": "number"}, "longest_recent_run_km": {"type": "number"},
         "level": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
         "recent_race_distance": {"type": "string", "enum": list(RACE_DISTANCES_M)}, "recent_race_time": {"type": "string"},
         "goal_time": {"type": "string"}, "include_strength": {"type": "boolean"}},
         "required": ["goal", "days_per_week", "current_weekly_km", "level"]}},
    {"name": "adapt_today_to_readiness", "description": "Ajusta el entreno de hoy según la readiness (HRV/FC/sueño).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "not_feeling_100", "description": "El atleta no está al 100%: reduce (o descanso activo) los próximos N días.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 14},
                                                         "mode": {"type": "string", "enum": ["reduce", "rest"]}}, "required": ["days"]}},
    {"name": "push_to_garmin", "description": "Envía entrenos (ids) al calendario de Garmin Connect para sincronizar con el reloj.",
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
        rows = S.wellness_rows(s, 14)
        return {"readiness": S.readiness_today(s), "last_14_days": rows}
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
        return S.move_workout(s, args["id"], args["date"])
    if name == "generate_plan":
        p = S.create_plan(s, args)
        return {k: v for k, v in p.items() if k != "weeks"} | {"n_weeks": len(p["weeks"])}
    if name == "adapt_today_to_readiness":
        return S.adapt_today(s, today.isoformat())
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
    base, key_env, _ = OPENAI_COMPAT[p]
    key = os.getenv("OPENRUN_API_KEY") or (os.getenv(key_env) if key_env else None) or "ollama"
    return openai.OpenAI(base_url=os.getenv("OPENRUN_BASE_URL", base), api_key=key)


def _dump_call(c) -> dict:
    # Keep provider extras (e.g. Gemini's extra_content.google.thought_signature, required on replay)
    try:
        d = c.model_dump(exclude_none=True)
        json.dumps(d)
        return d
    except Exception:  # noqa: BLE001
        return {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}


def _chat_openai_compat(s: Session, user_text: str) -> dict:
    """Same tool loop over the OpenAI chat-completions format (Gemini free tier, Ollama, Groq...).
    Messages are stored with role 'oa' so they never mix with Anthropic-format history."""
    import openai
    _save(s, "oa", [{"role": "user", "content": user_text}])
    client = _openai_client()
    model = provider_info()["model"]
    system = SYSTEM.format(today=dt.date.today().strftime("%A %d/%m/%Y"))
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
             for t in TOOLS]
    tool_log: list[dict] = []
    for _ in range(MAX_TOOL_ROUNDS):
        history = [m.content[0] for m in s.exec(select(ChatMessage).where(ChatMessage.role == "oa").order_by(ChatMessage.id)).all()]
        try:
            resp = client.chat.completions.create(model=model, messages=[{"role": "system", "content": system}, *history], tools=tools)
        except openai.AuthenticationError:
            return {"reply": f"Falta la API key para {provider()} o no es válida.", "tools": tool_log, "error": True}
        except openai.RateLimitError:
            return {"reply": "Límite del plan gratuito alcanzado; prueba en un rato.", "tools": tool_log, "error": True}
        except openai.APIConnectionError:
            return {"reply": f"No hay conexión con {provider()}" + (" (¿está Ollama arrancado?)" if provider() == "ollama" else "."), "tools": tool_log, "error": True}
        except openai.APIStatusError as e:
            return {"reply": f"Error del proveedor ({e.status_code}): {e.message}", "tools": tool_log, "error": True}
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        _save(s, "oa", [{"role": "assistant", "content": msg.content or "",
                         **({"tool_calls": [_dump_call(c) for c in calls]} if calls else {})}])
        if not calls:
            return {"reply": msg.content or "", "tools": tool_log}
        for c in calls:
            try:
                out = run_tool(s, c.function.name, json.loads(c.function.arguments or "{}"))
                content = json.dumps(out, default=str, ensure_ascii=False)[:60000]
                tool_log.append({"tool": c.function.name, "ok": True})
            except Exception as e:  # noqa: BLE001
                content = f"Error: {e}"
                tool_log.append({"tool": c.function.name, "ok": False, "error": str(e)})
            _save(s, "oa", [{"role": "tool", "tool_call_id": c.id, "content": content}])
    return {"reply": "He alcanzado el límite de pasos para esta petición.", "tools": tool_log}


def _chat_anthropic(s: Session, user_text: str) -> dict:
    """Run one user turn through the manual tool loop. History is append-only (thinking blocks preserved)."""
    _save(s, "user", [{"type": "text", "text": user_text}])
    client = _client()
    system = SYSTEM.format(today=dt.date.today().strftime("%A %d/%m/%Y"))
    tool_log: list[dict] = []
    for _ in range(MAX_TOOL_ROUNDS):
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
            return {"reply": "Falta la API key de Anthropic (ANTHROPIC_API_KEY) o no es válida.", "tools": tool_log, "error": True}
        except anthropic.RateLimitError:
            return {"reply": "Límite de uso de la API alcanzado; inténtalo en un momento.", "tools": tool_log, "error": True}
        except anthropic.APIStatusError as e:
            return {"reply": f"Error de la API ({e.status_code}): {e.message}", "tools": tool_log, "error": True}
        except anthropic.APIConnectionError:
            return {"reply": "No hay conexión con la API de Anthropic.", "tools": tool_log, "error": True}

        content = [b.model_dump(exclude_none=True) for b in resp.content]
        _save(s, "assistant", content)

        if resp.stop_reason == "refusal":
            return {"reply": "No puedo ayudar con esa petición.", "tools": tool_log}
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
    return {"reply": "He alcanzado el límite de pasos para esta petición.", "tools": tool_log}


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
