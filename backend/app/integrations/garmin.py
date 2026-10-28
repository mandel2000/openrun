"""Garmin Connect integration via python-garminconnect (unofficial API, mobile SSO tokens).

Garmin's official Health/Training APIs are only for approved business partners, so personal
projects use the same endpoints as the Connect app. Tokens are stored locally
(~/.openrun/garmin) and auto-refresh; credentials are never stored.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TOKEN_DIR = Path(os.getenv("OPENRUN_GARMIN_TOKENS", Path.home() / ".openrun" / "garmin"))

STEP_TYPES = {"warmup": (1, "warmup"), "cooldown": (2, "cooldown"), "run": (3, "interval"),
              "recovery": (4, "recovery"), "rest": (5, "rest"), "repeat": (6, "repeat")}
END_CONDITIONS = {"open": (1, "lap.button"), "time": (2, "time"), "distance": (3, "distance")}


# ---------------------------------------------------------------- workout conversion


def _speed(pace_s_per_km: float) -> float:
    return round(1000.0 / pace_s_per_km, 4)


def _step_to_garmin(step: dict, order: list[int], child_id: int | None) -> dict:
    order[0] += 1
    sid, skey = STEP_TYPES[step["kind"]]
    if step["kind"] == "repeat":
        order_here = order[0]
        group_id = order_here
        children = [_step_to_garmin(s, order, group_id) for s in step["steps"]]
        return {
            "type": "RepeatGroupDTO", "stepOrder": order_here, "childStepId": child_id,
            "stepType": {"stepTypeId": sid, "stepTypeKey": skey, "displayOrder": sid},
            "numberOfIterations": int(step["repeat"]), "smartRepeat": False,
            "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False},
            "endConditionValue": float(step["repeat"]), "workoutSteps": children,
        }
    cid, ckey = END_CONDITIONS[step.get("duration_type", "open")]
    out: dict[str, Any] = {
        "type": "ExecutableStepDTO", "stepOrder": order[0], "childStepId": child_id,
        "stepType": {"stepTypeId": sid, "stepTypeKey": skey, "displayOrder": sid},
        "endCondition": {"conditionTypeId": cid, "conditionTypeKey": ckey, "displayOrder": cid, "displayable": True},
        "endConditionValue": float(step.get("duration_value") or 0) if cid != 1 else None,
        "description": (step.get("note") or "")[:500] or None,
    }
    if step.get("pace_slow") and step.get("pace_fast"):
        # Garmin pace targets are speeds in m/s; slower pace = lower limit (targetValueOne)
        out["targetType"] = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}
        out["targetValueOne"] = _speed(step["pace_slow"])
        out["targetValueTwo"] = _speed(step["pace_fast"])
    elif step.get("hr_low") and step.get("hr_high"):
        out["targetType"] = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
        out["targetValueOne"] = float(step["hr_low"])
        out["targetValueTwo"] = float(step["hr_high"])
    else:
        out["targetType"] = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
    return out


def workout_to_garmin(workout: dict) -> dict:
    sport = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
    order = [0]
    steps = [_step_to_garmin(s, order, None) for s in workout["steps"]]
    name = workout["title"][:60]
    if workout.get("date"):
        name = f"OR {workout['date'][5:]} {name}"[:60]
    return {
        "workoutName": name,
        "description": (workout.get("description") or "")[:1000],
        "sportType": sport,
        "estimatedDurationInSecs": int(workout.get("duration_min", 0) * 60),
        "estimatedDistanceInMeters": float(workout.get("distance_km", 0) * 1000),
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport, "workoutSteps": steps}],
    }


# ---------------------------------------------------------------- client


class GarminError(RuntimeError):
    pass


class GarminService:
    def __init__(self, token_dir: Path = TOKEN_DIR) -> None:
        self.token_dir = token_dir
        self._client = None
        self._pending_mfa: tuple[Any, Any] | None = None

    # --- auth
    def _new(self, email=None, password=None):
        from garminconnect import Garmin
        return Garmin(email=email, password=password, return_on_mfa=True)

    def status(self) -> dict:
        if self._client:
            return {"connected": True, "name": getattr(self._client, "full_name", None)}
        if (self.token_dir / "garmin_tokens.json").exists():
            try:
                self.client()
                return {"connected": True, "name": getattr(self._client, "full_name", None)}
            except Exception as e:  # noqa: BLE001
                return {"connected": False, "error": str(e)}
        return {"connected": False}

    def login(self, email: str, password: str) -> dict:
        self.token_dir.mkdir(parents=True, exist_ok=True)
        g = self._new(email, password)
        status, state = g.login(str(self.token_dir))
        if status == "needs_mfa":
            self._pending_mfa = (g, state)
            return {"connected": False, "needs_mfa": True}
        # With return_on_mfa=True the library returns early on a non-MFA login: it neither
        # persists tokens nor loads the profile, so do both here.
        self._persist(g)
        self._client = g
        return {"connected": True, "name": getattr(g, "full_name", None)}

    def _persist(self, g) -> None:
        try:
            g.client.dump(str(self.token_dir))
        except Exception:  # noqa: BLE001 - token persistence is best effort
            log.warning("could not persist garmin tokens", exc_info=True)
        if not getattr(g, "full_name", None) and hasattr(g, "_load_profile_and_settings"):
            try:
                g._load_profile_and_settings()
            except Exception:  # noqa: BLE001
                log.warning("could not load garmin profile", exc_info=True)

    def submit_mfa(self, code: str) -> dict:
        if not self._pending_mfa:
            raise GarminError("No hay login pendiente de MFA")
        g, state = self._pending_mfa
        g.resume_login(state, code)
        self._persist(g)
        self._pending_mfa = None
        self._client = g
        return {"connected": True, "name": getattr(g, "full_name", None)}

    def logout(self) -> None:
        if self._client:
            try:
                self._client.logout()
            except Exception:  # noqa: BLE001
                pass
        self._client = None
        try:
            (self.token_dir / "garmin_tokens.json").unlink()
        except OSError:
            pass

    def client(self):
        if self._client is None:
            if not (self.token_dir / "garmin_tokens.json").exists():
                raise GarminError("Garmin no conectado")
            g = self._new()
            g.login(str(self.token_dir))
            self._client = g
        return self._client

    # --- workouts
    def push_workout(self, workout: dict, schedule: bool = True) -> dict:
        c = self.client()
        res = c.upload_workout(workout_to_garmin(workout))
        wid = res.get("workoutId")
        if schedule and workout.get("date") and wid:
            c.schedule_workout(wid, workout["date"])
        return {"workout_id": wid}

    def delete_workout(self, workout_id: int | str) -> None:
        self.client().delete_workout(workout_id)

    # --- data
    def fetch_activities(self, start: dt.date, end: dt.date) -> list[dict]:
        raw = self.client().get_activities_by_date(start.isoformat(), end.isoformat()) or []
        return [normalize_activity(a) for a in raw]

    def fetch_all_activities(self, max_n: int = 5000) -> list[dict]:
        """Whole history (summaries only), newest first."""
        c, out, start = self.client(), [], 0
        while start < max_n:
            page = c.get_activities(start, 100) or []
            out += [normalize_activity(a) for a in page]
            if len(page) < 100:
                break
            start += 100
        return out

    def fetch_laps(self, external_id: str) -> list[dict]:
        """Raw lapDTOs of a Garmin activity (one lap per executed workout step)."""
        aid = external_id.split(":", 1)[1]
        return (self.client().get_activity_splits(aid) or {}).get("lapDTOs") or []

    def fetch_streams(self, external_id: str) -> dict:
        """Second-by-second-ish series of an activity (Garmin returns up to 2000 samples)."""
        aid = external_id.split(":", 1)[1]
        return streams_from_details(self.client().get_activity_details(aid, 2000, 0))

    def fetch_personal_records(self) -> dict:
        """Garmin's own all-time running PRs: {distance_key: {time_s, date, activity_id}}."""
        keys = {1: "1k", 2: "mile", 3: "5k", 4: "10k", 5: "half", 6: "marathon"}
        out = {}
        for r in self.client().get_personal_record() or []:
            k = keys.get(r.get("typeId"))
            if k and r.get("value") and (r.get("activityType") or "").endswith("running"):
                out[k] = {"time_s": r["value"], "date": (r.get("activityStartDateTimeLocalFormatted") or "")[:10],
                          "garmin_activity_id": r.get("activityId"), "name": r.get("activityName")}
        return out

    def fetch_wellness(self, day: dt.date) -> dict:
        c = self.client()
        d = day.isoformat()
        row: dict[str, Any] = {"date": d, "source": "garmin"}
        try:
            hrv = c.get_hrv_data(d) or {}
            summ = hrv.get("hrvSummary") or {}
            row["hrv_rmssd"] = summ.get("lastNightAvg")
            row["hrv_status"] = summ.get("status")
        except Exception:  # noqa: BLE001
            log.debug("hrv fetch failed", exc_info=True)
        try:
            sleep = (c.get_sleep_data(d) or {}).get("dailySleepDTO") or {}
            row["sleep_score"] = ((sleep.get("sleepScores") or {}).get("overall") or {}).get("value")
            row["sleep_hours"] = round((sleep.get("sleepTimeSeconds") or 0) / 3600, 2) or None
        except Exception:  # noqa: BLE001
            log.debug("sleep fetch failed", exc_info=True)
        try:
            stats = c.get_stats(d) or {}
            row["rest_hr"] = stats.get("restingHeartRate")
            row["body_battery"] = stats.get("bodyBatteryMostRecentValue")
            row["stress"] = stats.get("averageStressLevel")
        except Exception:  # noqa: BLE001
            log.debug("stats fetch failed", exc_info=True)
        try:
            tr = c.get_training_readiness(d) or []
            if tr:
                row["training_readiness"] = tr[0].get("score")
        except Exception:  # noqa: BLE001
            log.debug("readiness fetch failed", exc_info=True)
        return row

    def fetch_profile_metrics(self) -> dict:
        c = self.client()
        out: dict[str, Any] = {}
        try:
            mm = c.get_max_metrics(dt.date.today().isoformat())
            if isinstance(mm, list) and mm:
                out["vo2max"] = ((mm[0].get("generic") or {}).get("vo2MaxPreciseValue"))
        except Exception:  # noqa: BLE001
            pass
        try:
            lt = c.get_lactate_threshold()
            shr = (lt or {}).get("speed_and_heart_rate") or {}
            out["lthr"] = shr.get("heartRate")
        except Exception:  # noqa: BLE001
            pass
        try:
            rp = c.get_race_predictions()
            if isinstance(rp, dict):
                out["race_predictions"] = {k: rp.get(k) for k in ("time5K", "time10K", "timeHalfMarathon", "timeMarathon")}
        except Exception:  # noqa: BLE001
            pass
        return out


def normalize_activity(a: dict) -> dict:
    type_key = ((a.get("activityType") or {}).get("typeKey") or "").lower()
    sport = "running" if "running" in type_key or type_key in ("track_running", "treadmill_running", "trail_running") else type_key
    start = a.get("startTimeLocal") or ""
    return {
        "external_id": f"garmin:{a.get('activityId')}",
        "date": start[:10],
        "start_time": start,
        "name": a.get("activityName"),
        "sport": sport,
        "distance_m": a.get("distance") or 0,
        "duration_s": a.get("movingDuration") or a.get("duration") or 0,
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "elevation_gain": a.get("elevationGain"),
        "avg_cadence": a.get("averageRunningCadenceInStepsPerMinute"),
        "training_effect": a.get("aerobicTrainingEffect"),
        "anaerobic_effect": a.get("anaerobicTrainingEffect"),
        "training_load": a.get("activityTrainingLoad"),
        "vo2max": a.get("vO2MaxValue"),
        "start_lat": a.get("startLatitude"),
        "start_lon": a.get("startLongitude"),
        # fastest contiguous segment per distance, e.g. {"1000": 257.9, "5000": 1376.3}
        "best_efforts": {k.split("_", 1)[1]: v for k, v in a.items() if k.startswith("fastestSplit_") and v},
        "source": "garmin",
    }


STREAM_KEYS = {"t": "sumDuration", "d": "sumDistance", "hr": "directHeartRate", "speed": "directSpeed",
               "gap": "directGradeAdjustedSpeed", "ele": "directElevation", "cad": "directDoubleCadence",
               "lat": "directLatitude", "lon": "directLongitude", "power": "directPower", "stride": "directStrideLength",
               "gct": "directGroundContactTime", "vo": "directVerticalOscillation"}


def streams_from_details(details: dict, max_points: int = 900) -> dict:
    idx = {m["key"]: m["metricsIndex"] for m in details.get("metricDescriptors") or []}
    rows = [r.get("metrics") or [] for r in details.get("activityDetailMetrics") or []]
    out: dict[str, list] = {}
    for k, key in STREAM_KEYS.items():
        i = idx.get(key)
        if i is None:
            continue
        col = [r[i] if i < len(r) else None for r in rows]
        if any(v not in (None, 0, 0.0) for v in col):
            out[k] = col
    n = len(rows)
    if n > max_points:  # keep evenly spaced samples
        keep = [round(j * (n - 1) / (max_points - 1)) for j in range(max_points)]
        out = {k: [v[j] for j in keep] for k, v in out.items()}
    rnd = {"lat": 5, "lon": 5, "d": 1, "t": 1, "speed": 3, "gap": 3, "ele": 1, "stride": 1, "gct": 0, "vo": 1}
    return {k: [None if x is None else round(x, rnd.get(k, 0)) for x in v] for k, v in out.items()}


class _PerUser:
    """`garmin.<method>` acts on the current user's Garmin account (see app/tenancy.py).
    User 1 keeps the original token folder, so single-user installs keep their login."""

    def __init__(self) -> None:
        self._services: dict[int, GarminService] = {}

    def for_user(self, uid: int) -> GarminService:
        if uid not in self._services:
            self._services[uid] = GarminService(TOKEN_DIR if uid == 1 else TOKEN_DIR / "users" / str(uid))
        return self._services[uid]

    def forget(self, uid: int) -> None:
        svc = self.for_user(uid)
        svc._client = None
        import shutil
        if uid != 1:
            shutil.rmtree(svc.token_dir, ignore_errors=True)
        self._services.pop(uid, None)

    def __getattr__(self, name):
        from ..tenancy import current_user_id
        return getattr(self.for_user(current_user_id()), name)


garmin = _PerUser()
