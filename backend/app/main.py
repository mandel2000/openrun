from __future__ import annotations

import datetime as dt
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session

from . import auth, scheduler
from . import services as S
from .ai import coach
from .db import get_session, init_db
from .integrations import orycron, zepp
from .integrations.garmin import garmin, workout_to_garmin
from .training import load
from .training.vdot import RACE_DISTANCES_M, parse_time, race_predictions, training_paces, vdot_from_race


@asynccontextmanager
async def lifespan(_: FastAPI):
    auth.check_config()
    init_db()
    stop = threading.Event()
    if os.getenv("OPENRUN_SCHEDULER", "1") == "1":
        scheduler.start(stop)
    yield
    stop.set()


app = FastAPI(title="OpenRun", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
DB = Depends(get_session)


# ---------------------------------------------------------------- access control (see app/auth.py)

SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY"}


@app.middleware("http")
async def access_control(request: Request, call_next):
    path = request.url.path
    public = path in ("/api/health",) or path.startswith("/api/auth")
    if path.startswith("/api/") and not public and not auth.authed(request):
        msg = "Inicia sesión" if auth.PASSWORD else "Acceso remoto desactivado: define OPENRUN_PASSWORD (u OPENRUN_PIN en casa)"
        return JSONResponse({"detail": msg}, status_code=401, headers=SECURITY_HEADERS)
    resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    if auth.is_https(request):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


@app.get("/api/health")
def health():
    return {"ok": True}


class LoginIn(BaseModel):
    pin: str


@app.get("/api/auth")
def auth_status(request: Request):
    return {"authed": auth.authed(request), "local": auth.is_local(request), "pin_enabled": bool(auth.PASSWORD),
            "kind": "password" if len(auth.PASSWORD) > 6 else "pin"}


@app.post("/api/auth")
def auth_login(body: LoginIn, request: Request):
    ok, err = auth.check_password(request, body.pin)
    if not ok:
        raise HTTPException(429 if err and err.startswith("Demasiados") else 401, err)
    resp = JSONResponse({"authed": True})
    resp.set_cookie(auth.COOKIE, auth.make_session(), max_age=auth.SESSION_DAYS * 86400, httponly=True,
                    samesite="lax", secure=auth.is_https(request))
    return resp


@app.post("/api/auth/logout")
def auth_logout():
    resp = JSONResponse({"authed": False})
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/api/network")
def network_info(request: Request):
    """LAN URLs to open OpenRun from the phone (only meaningful when bound to 0.0.0.0)."""
    import socket

    ips = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))  # TEST-NET, nothing is sent
            ips.add(sock.getsockname()[0])
    except OSError:
        pass
    host = os.getenv("OPENRUN_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    public_url = os.getenv("OPENRUN_PUBLIC_URL", "")
    return {"lan_enabled": host not in ("127.0.0.1", "localhost") and not public_url, "pin_enabled": bool(auth.PASSWORD),
            "urls": [public_url] if public_url else [f"http://{ip}:{port}" for ip in sorted(ips)],
            "public": bool(public_url), "local": auth.is_local(request)}


# ---------------------------------------------------------------- settings, daily routine, analysis, heat


class SettingsIn(BaseModel):
    auto_sync: bool | None = None
    sync_time: str | None = None
    auto_adapt: bool | None = None
    auto_push: bool | None = None
    auto_pace: bool | None = None
    heat_adjust: bool | None = None
    run_hour: int | None = None
    lat: float | None = None
    lon: float | None = None


@app.get("/api/settings")
def settings_get(s: Session = DB):
    return S.get_settings(s)


@app.put("/api/settings")
def settings_put(body: SettingsIn, s: Session = DB):
    d = body.model_dump(exclude_unset=True)
    if "sync_time" in d and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", d["sync_time"] or ""):
        raise HTTPException(400, "Hora no válida (HH:MM)")
    if "run_hour" in d and not 0 <= (d["run_hour"] or 0) <= 23:
        raise HTTPException(400, "Hora no válida")
    return S.update_settings(s, **d)


@app.post("/api/daily/run")
def daily_run(s: Session = DB):
    return S.daily_routine(s, force=True)


@app.get("/api/daily/log")
def daily_log(s: Session = DB):
    return S.meta_get(s, "daily_log")


@app.get("/api/activities/{aid}/analysis")
def activity_analysis(aid: int, refresh: bool = False, s: Session = DB):
    from .db import Activity

    act = s.get(Activity, aid)
    if not act:
        raise HTTPException(404)
    if act.data.get("analysis") and not refresh:
        return act.data["analysis"]
    try:
        res = S.analyze_activity(s, act)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"No se pudieron leer las vueltas de Garmin: {e}") from e
    if res is None:
        raise HTTPException(400, "Solo hay análisis por vueltas para actividades de Garmin")
    return res


@app.get("/api/pace-insights")
def pace_insights_get(s: Session = DB):
    return {**S.pace_insights(s, apply=False), "auto": S.get_settings(s)["auto_pace"]}


@app.post("/api/pace-insights/apply")
def pace_insights_apply(s: Session = DB):
    return S.pace_insights(s, apply=True)


@app.get("/api/weather")
def weather(date: str | None = None, s: Session = DB):
    try:
        return S.weather_for(s, date or dt.date.today().isoformat()) or {"available": False}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)}


@app.post("/api/heat/apply")
def heat_apply(s: Session = DB):
    changes = S.apply_heat(s)
    pushed = S.push_changed(s, 2) if garmin.status().get("connected") else []
    return {"changes": changes, "pushed": sum(1 for p in pushed if p["ok"])}


# ---------------------------------------------------------------- athlete


class AthleteIn(BaseModel):
    name: str | None = None
    sex: str | None = None
    age: int | None = None
    max_hr: int | None = None
    rest_hr: int | None = None
    lthr: int | None = None
    weekly_km: float | None = None


@app.get("/api/athlete")
def get_athlete(s: Session = DB):
    return S.athlete_profile(s)


@app.put("/api/athlete")
def put_athlete(body: AthleteIn, s: Session = DB):
    return S.update_athlete(s, **body.model_dump())


class RaceIn(BaseModel):
    distance: str
    time: str
    recalibrate: bool = True


@app.post("/api/athlete/race-result")
def race_result(body: RaceIn, s: Session = DB):
    if body.distance not in RACE_DISTANCES_M:
        raise HTTPException(400, "distancia no válida")
    v = vdot_from_race(RACE_DISTANCES_M[body.distance], parse_time(body.time))
    if body.recalibrate:
        return S.recalibrate_paces(s, v, f"race {body.distance} {body.time}")
    return S.set_race_result(s, body.distance, body.time)


@app.get("/api/vdot")
def calc_vdot(distance: str, time: str):
    v = vdot_from_race(RACE_DISTANCES_M[distance], parse_time(time))
    return {"vdot": round(v, 1), "paces": training_paces(v).as_dict(), "predictions": race_predictions(v)}


@app.get("/api/fitness-estimate")
def fitness_estimate(s: Session = DB):
    return S.fitness_estimate(s)


# ---------------------------------------------------------------- plan


class PlanIn(BaseModel):
    goal: str
    start_date: str | None = None
    race_date: str | None = None
    weeks: int | None = None
    days_per_week: int = 4
    long_run_day: int = 6
    current_weekly_km: float = 20
    longest_recent_run_km: float = 10
    level: str = "intermediate"
    recent_race_distance: str | None = None
    recent_race_time: str | None = None
    goal_time: str | None = None
    include_strength: bool = True
    name: str | None = None


@app.post("/api/plan")
def create_plan(body: PlanIn, s: Session = DB):
    try:
        return S.create_plan(s, body.model_dump(exclude_none=True))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/plan")
def get_plan(s: Session = DB):
    return S.plan_overview(s)


@app.get("/api/workouts")
def workouts(start: str, end: str, s: Session = DB):
    return S.list_workouts(s, start, end)


@app.get("/api/workouts/{wid}/garmin-json")
def workout_garmin_json(wid: int, s: Session = DB):
    from .db import PlannedWorkout
    pw = s.get(PlannedWorkout, wid)
    if not pw:
        raise HTTPException(404)
    return workout_to_garmin({**pw.data, "date": pw.date})


class ExtraIn(BaseModel):
    date: str
    km: float | None = None


@app.post("/api/workouts/extra")
def add_extra(body: ExtraIn, s: Session = DB):
    return S.add_extra_run(s, body.date, body.km)


class MoveIn(BaseModel):
    date: str


@app.post("/api/workouts/{wid}/move")
def move(wid: int, body: MoveIn, s: Session = DB):
    return S.move_workout(s, wid, body.date)


@app.post("/api/workouts/{wid}/skip")
def skip(wid: int, s: Session = DB):
    from .db import PlannedWorkout
    pw = s.get(PlannedWorkout, wid)
    if not pw:
        raise HTTPException(404)
    pw.status = "skipped"
    s.add(pw)
    s.commit()
    return S.workout_dict(pw)


@app.delete("/api/workouts/{wid}")
def delete(wid: int, s: Session = DB):
    S.delete_workout(s, wid)
    return {"ok": True}


class FeelIn(BaseModel):
    days: int = 3
    mode: str = "reduce"


@app.post("/api/not-feeling-100")
def not_feeling(body: FeelIn, s: Session = DB):
    return S.not_feeling_well(s, body.days, body.mode)


@app.post("/api/adapt-today")
def adapt_today(s: Session = DB):
    return S.adapt_today(s)


# ---------------------------------------------------------------- garmin


class GarminLogin(BaseModel):
    email: str
    password: str


class MfaIn(BaseModel):
    code: str


@app.get("/api/garmin/status")
def garmin_status(s: Session = DB):
    return {**garmin.status(), "last_sync": S.meta_get(s, "garmin_metrics").get("synced_at")}


@app.post("/api/garmin/login")
def garmin_login(body: GarminLogin):
    try:
        return garmin.login(body.email, body.password)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Login Garmin falló: {e}") from e


@app.post("/api/garmin/mfa")
def garmin_mfa(body: MfaIn):
    try:
        return garmin.submit_mfa(body.code)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@app.post("/api/garmin/logout")
def garmin_logout():
    garmin.logout()
    return {"ok": True}


@app.post("/api/garmin/sync")
def garmin_sync(days: int = 14, full: bool = False, s: Session = DB):
    try:
        return S.sync_garmin(s, days, full)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Sync falló: {e}") from e


class PushIn(BaseModel):
    ids: list[int] | None = None
    days: int = 7


@app.post("/api/garmin/push")
def garmin_push(body: PushIn, s: Session = DB):
    return S.push_to_garmin(s, body.ids) if body.ids else S.push_upcoming(s, body.days)


# ---------------------------------------------------------------- wellness / helio strap


@app.post("/api/wellness/import")
async def wellness_import(file: UploadFile = File(...), s: Session = DB):
    rows = zepp.parse_upload(file.filename or "", await file.read())
    for r in rows:
        S.upsert_wellness(s, r)
    return {"imported_days": len(rows), "sample": rows[-3:]}


class HrvReading(BaseModel):
    rr_ms: list[float]
    date: str | None = None
    avg_hr: float | None = None


@app.post("/api/wellness/hrv-reading")
def hrv_reading(body: HrvReading, s: Session = DB):
    """Morning HRV check from the Helio Strap's RR intervals (Web Bluetooth)."""
    value = load.rmssd(body.rr_ms)
    if value is None:
        raise HTTPException(400, "Lectura insuficiente o con artefactos: repite 2-3 min tumbado y quieto.")
    row: dict[str, Any] = {"date": body.date or dt.date.today().isoformat(), "source": "ble", "hrv_rmssd": round(value, 1)}
    if body.avg_hr:
        row["rest_hr"] = round(body.avg_hr)
    S.upsert_wellness(s, row)
    return {"rmssd": round(value, 1), "ln_rmssd": round(__import__("math").log(value), 2), "readiness": S.readiness_today(s)}


@app.get("/api/wellness")
def wellness(days: int = 60, s: Session = DB):
    return {"rows": S.wellness_rows(s, days), "readiness": S.readiness_today(s)}


@app.get("/api/load")
def training_load(days: int = 90, s: Session = DB):
    return S.training_load(s, days)


@app.get("/api/activities")
def activities(days: int = 28, s: Session = DB):
    return S.recent_activities(s, days)


# ---------------------------------------------------------------- AI coach


class ChatIn(BaseModel):
    message: str


@app.post("/api/chat")
def chat(body: ChatIn, s: Session = DB):
    return coach.chat(s, body.message)


@app.get("/api/chat")
def chat_history(s: Session = DB):
    return coach.visible_history(s)


@app.delete("/api/chat")
def chat_reset(s: Session = DB):
    coach.reset(s)
    return {"ok": True}


# ---------------------------------------------------------------- static frontend (production build)

# ---------------------------------------------------------------- records, predictions, races


@app.get("/api/coach/info")
def coach_info():
    import sys
    backend = Path(__file__).resolve().parents[1]
    public_url = os.getenv("OPENRUN_PUBLIC_URL", "")
    # Ready-to-paste MCP config for Claude Desktop / Gemini CLI. On a server, the MCP process runs on
    # the user's computer (from a local clone) and talks to this server with the API token.
    mcp = ({"remote": True, "url": public_url, "token_set": bool(auth.API_TOKEN)} if public_url
           else {"remote": False, "command": sys.executable, "args": ["-m", "app.mcp_server"], "cwd": str(backend)})
    return {**coach.provider_info(), "mcp": mcp}


class ToolIn(BaseModel):
    args: dict[str, Any] = {}


@app.post("/api/tools/{name}")
def run_tool(name: str, body: ToolIn, s: Session = DB):
    """Coach tools over HTTP (used by the local MCP server when OpenRun runs on a server)."""
    if name not in {t["name"] for t in coach.TOOLS}:
        raise HTTPException(404, "herramienta desconocida")
    try:
        return {"ok": True, "result": coach.run_tool(s, name, body.args)}
    except Exception as e:  # noqa: BLE001 - report to the model like the in-app coach does
        return {"ok": False, "error": str(e)}


class RecalIn(BaseModel):
    vdot: float
    source: str


@app.post("/api/athlete/recalibrate")
def recalibrate(body: RecalIn, s: Session = DB):
    if not 20 <= body.vdot <= 85:
        raise HTTPException(400, "VDOT fuera de rango")
    return S.recalibrate_paces(s, body.vdot, body.source)


@app.post("/api/import/history")
async def import_history(files: list[UploadFile] = File(...)):
    """Strava bulk export (.zip), Garmin export (.zip) or loose .fit/.gpx/.tcx(.gz) files.
    Uploads are spooled to temp files (exports can be GBs) and processed in the background."""
    import shutil
    import tempfile

    saved: list[tuple[str, str]] = []
    for f in files:
        name = f.filename or "upload"
        if not re.search(r"\.(zip|fit|gpx|tcx)(\.gz)?$", name, re.I):
            raise HTTPException(400, f"Formato no soportado: {name}")
        fd, path = tempfile.mkstemp(prefix="openrun-import-", suffix="-" + Path(name).name)
        with open(fd, "wb") as out:
            shutil.copyfileobj(f.file, out, 1024 * 1024)
        saved.append((name, path))
    return {"job": S.start_import_job(saved, [p for _, p in saved])}


@app.get("/api/import/history/{job_id}")
def import_status(job_id: str):
    job = S.IMPORT_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "importación no encontrada")
    return job


@app.get("/api/records")
def records(s: Session = DB):
    return S.personal_records(s)


@app.get("/api/predictions")
def predictions(s: Session = DB):
    return S.race_time_predictions(s)


class RaceEntryIn(BaseModel):
    name: str | None = None
    date: str | None = None
    distance_m: float | None = None
    priority: str | None = None
    location: str | None = None
    url: str | None = None
    source: str | None = None
    external_id: str | None = None
    goal_time: str | None = None
    result_time: str | None = None
    notes: str | None = None


def _race_fields(body: RaceEntryIn) -> dict:
    d = body.model_dump(exclude_none=True)
    if "goal_time" in d:
        d["goal_time_s"] = parse_time(d.pop("goal_time"))
    if "result_time" in d:
        d["result_time_s"] = parse_time(d.pop("result_time"))
    return d


@app.get("/api/races")
def races(s: Session = DB):
    return S.list_races(s)


@app.post("/api/races")
def race_add(body: RaceEntryIn, s: Session = DB):
    d = _race_fields(body)
    if not d.get("name") or not d.get("date"):
        raise HTTPException(400, "nombre y fecha obligatorios")
    try:
        return S.add_race(s, d.pop("name"), d.pop("date"), d.pop("distance_m", None), d.pop("priority", "B"), **d)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/races/{rid}")
def race_update(rid: int, body: RaceEntryIn, s: Session = DB):
    try:
        return S.update_race(s, rid, **_race_fields(body))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.delete("/api/races/{rid}")
def race_delete(rid: int, s: Session = DB):
    S.delete_race(s, rid)
    return {"ok": True}


@app.get("/api/race-calendar")
def race_calendar(q: str = "", all: bool = False):
    try:
        items = orycron.upcoming(include_non_running=all)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"No se pudo leer el calendario de Orycron: {e}") from e
    ql = q.lower().strip()
    return [i for i in items if not ql or ql in i["name"].lower()]


@app.get("/api/race-calendar/{eid}")
def race_calendar_event(eid: str):
    try:
        return orycron.event(eid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"No se pudo leer la competición: {e}") from e


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and f.resolve().is_relative_to(DIST.resolve()):
            if path == "sw.js":  # must always be revalidated so new builds roll out
                return FileResponse(f, headers={"Cache-Control": "no-cache"}, media_type="text/javascript")
            if path.endswith(".webmanifest"):
                return FileResponse(f, media_type="application/manifest+json")
            return FileResponse(f)
        # index.html must not be cached: it points to the hashed bundle of the current build
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
