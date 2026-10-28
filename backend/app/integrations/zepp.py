"""Amazfit Helio Strap / Zepp data import.

Zepp has no public API. Three supported paths:
1. Live BLE: the strap broadcasts the standard Heart Rate Service (0x180D) incl. RR intervals.
   The web UI reads it via Web Bluetooth for a morning HRV check (RMSSD computed server-side),
   and the Garmin 265 can pair it as an external HR sensor during runs.
2. Zepp data export (Zepp app > Profile > Settings > Account > Export data / user.huami.com):
   a zip of CSVs (SLEEP, HEARTRATE_AUTO, HRV if available...). Upload the zip or any CSV.
3. Any CSV with a date column and HRV/RHR/sleep columns (e.g. Health Connect exports).
"""

from __future__ import annotations

import csv
import io
import statistics
import zipfile
from collections import defaultdict


def _norm(h: str) -> str:
    return h.strip().lower().replace(" ", "").replace("_", "")


def _find(headers: list[str], *cands: str) -> str | None:
    nh = {_norm(h): h for h in headers}
    for c in cands:
        for k, orig in nh.items():
            if c in k:
                return orig
    return None


def _num(x) -> float | None:
    try:
        v = float(str(x).strip())
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def parse_csv(text: str) -> list[dict]:
    """Return per-day wellness rows: {date, hrv_rmssd?, rest_hr?, sleep_score?, sleep_hours?}."""
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    date_col = _find(headers, "date", "day", "timestamp", "time")
    if not date_col:
        return []
    hrv_col = _find(headers, "rmssd", "hrv")
    rhr_col = _find(headers, "restingheartrate", "restinghr", "rhr", "resting")
    score_col = _find(headers, "sleepscore", "score")
    hr_col = _find(headers, "heartrate") if not rhr_col else None
    deep, light, rem = _find(headers, "deepsleep"), _find(headers, "shallowsleep", "lightsleep"), _find(headers, "remtime", "rem")
    per: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in reader:
        raw = (row.get(date_col) or "").strip()
        if raw.isdigit():  # unix timestamp
            import datetime as dt
            ts = int(raw) / (1000 if len(raw) > 10 else 1)
            day = dt.datetime.fromtimestamp(ts).date().isoformat()
        else:
            day = raw[:10]
        if len(day) != 10:
            continue
        d = per[day]
        for key, col in (("hrv", hrv_col), ("rhr", rhr_col), ("score", score_col), ("hr", hr_col)):
            if col and (v := _num(row.get(col))) is not None and v > 0:
                d[key].append(v)
        if deep or light:
            mins = sum(_num(row.get(c)) or 0 for c in (deep, light, rem) if c)
            if mins:
                d["sleep_min"].append(mins)
    out = []
    for day, d in sorted(per.items()):
        r: dict = {"date": day, "source": "zepp"}
        if d["hrv"]:
            r["hrv_rmssd"] = round(statistics.mean(d["hrv"]), 1)
        if d["rhr"]:
            r["rest_hr"] = round(min(d["rhr"]))
        elif len(d["hr"]) >= 30:  # continuous HR: robust low percentile as RHR proxy
            hr = sorted(d["hr"])
            r["rest_hr"] = round(hr[max(0, int(len(hr) * 0.05) - 1)])
        if d["score"] and score_col and "sleep" in _norm(score_col):
            r["sleep_score"] = round(statistics.mean(d["score"]))
        if d["sleep_min"]:
            r["sleep_hours"] = round(sum(d["sleep_min"]) / 60, 2)
        if len(r) > 2:
            out.append(r)
    return out


def parse_upload(filename: str, content: bytes) -> list[dict]:
    if filename.lower().endswith(".zip"):
        merged: dict[str, dict] = {}
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for name in z.namelist():
                if name.lower().endswith(".csv"):
                    for r in parse_csv(z.read(name).decode("utf-8-sig", errors="replace")):
                        merged.setdefault(r["date"], {}).update(r)
        return [merged[d] for d in sorted(merged)]
    return parse_csv(content.decode("utf-8-sig", errors="replace"))
