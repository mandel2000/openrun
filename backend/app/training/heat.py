"""Heat adjustment of pace targets (like Runna's "Adapt for Heat").

Evidence: running performance falls as heat stress rises above ~10-15 °C, mostly through
cardiovascular strain and thermoregulation; the effect grows with humidity (Ely et al. 2007,
marathon times vs WBGT; El Helou et al. 2012, 1.8 M marathon results, optimum ~4-10 °C;
Mantzios et al. 2022 meta-analysis). For training, the practical rule used by coaches is the
temperature + dew point sum in °F (Hadley), which tracks heat stress better than temperature
alone. The slowdown keeps the physiological intent (same effort/HR) of each session.
"""

from __future__ import annotations

import time

import httpx

# (upper bound of T+Td in °F, % pace slowdown) — midpoints of the Hadley ranges
HADLEY = [(100, 0.0), (110, 0.5), (120, 1.5), (130, 2.5), (140, 3.8), (150, 5.3), (160, 7.0), (170, 9.0), (180, 11.0)]
TOO_HOT = 180  # above this, hard running is not advised: swap quality for easy/indoor


def c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def slowdown_pct(temp_c: float, dew_c: float) -> tuple[float, float]:
    """Returns (% slowdown, T+Td in °F)."""
    s = c_to_f(temp_c) + c_to_f(dew_c)
    for bound, pct in HADLEY:
        if s <= bound:
            return pct, round(s)
    return 12.0, round(s)


def scale_steps(steps: list[dict], pct: float) -> list[dict]:
    out = []
    for st in steps:
        st = dict(st)
        if st.get("kind") == "repeat":
            st["steps"] = scale_steps(st.get("steps") or [], pct)
        elif st.get("pace_slow") and st.get("pace_fast"):
            st["pace_slow"] = round(st["pace_slow"] * (1 + pct / 100), 1)
            st["pace_fast"] = round(st["pace_fast"] * (1 + pct / 100), 1)
        out.append(st)
    return out


_cache: dict[tuple, tuple[float, dict]] = {}


def forecast(lat: float, lon: float) -> dict:
    """Hourly temperature and dew point for 3 days from Open-Meteo (free, no key). Cached 1 h."""
    key = (round(lat, 2), round(lon, 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
        "latitude": key[0], "longitude": key[1], "hourly": "temperature_2m,dew_point_2m,relative_humidity_2m",
        "timezone": "auto", "forecast_days": 3})
    r.raise_for_status()
    h = r.json()["hourly"]
    data = {t: {"temp": tc, "dew": td, "rh": rh} for t, tc, td, rh in zip(h["time"], h["temperature_2m"], h["dew_point_2m"], h["relative_humidity_2m"])}
    _cache[key] = (time.time(), data)
    return data


def at(fc: dict, date: str, hour: int) -> dict | None:
    return fc.get(f"{date}T{hour:02d}:00")
