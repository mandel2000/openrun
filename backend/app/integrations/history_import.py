"""Import old running history from a Strava bulk export (.zip) or loose FIT / GPX / TCX files.

Each run becomes an activity in the same shape as a normalized Garmin activity, including
`best_efforts` ({metres: seconds}) computed from the distance/time stream with a sliding window,
so PRs from previous years show up in Progreso › Récords.

- FIT/TCX: distance comes from the device (GPS filtered / footpod), which is what the watch uses.
- GPX: distance from lat/lon (haversine) after light smoothing; GPS-only best efforts are less
  precise, so implausible speeds are dropped and efforts are sanity-checked.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Iterator

EFFORT_DISTANCES = (1000, 1609, 5000, 10000, 21097, 42195)
MAX_FILE_BYTES = 64 * 1024 * 1024  # per decompressed member; guards against zip bombs
MAX_SPEED = 8.5  # m/s (~1:58/km); GPS jumps above this are discarded
# Fastest plausible times (s) per distance, a bit under world records: anything faster is a GPS artefact
MIN_PLAUSIBLE = {1000: 140, 1609: 225, 5000: 750, 10000: 1560, 21097: 3420, 42195: 7200}
RUN_TYPES = re.compile(r"\b(run|running|carrera|correr|trail|treadmill|cinta|virtual ?run)\b", re.I)


# ---------------------------------------------------------------- streams -> best efforts


def best_efforts(times: list[float], dists: list[float]) -> dict[str, float]:
    """Fastest contiguous segment for each standard distance. times/dists are cumulative (s, m)."""
    out: dict[str, float] = {}
    n = len(times)
    if n < 2:
        return out
    for D in EFFORT_DISTANCES:
        if dists[-1] - dists[0] < D:
            continue
        best = math.inf
        i = 0
        for j in range(1, n):
            target = dists[j] - D  # segment must start at or before this distance
            if target < dists[0]:
                continue
            while i + 1 < j and dists[i + 1] <= target:
                i += 1
            span = dists[i + 1] - dists[i]
            frac = (target - dists[i]) / span if span > 0 else 0
            t_start = times[i] + (times[i + 1] - times[i]) * min(max(frac, 0), 1)
            best = min(best, times[j] - t_start)
        if best < math.inf and best >= MIN_PLAUSIBLE[D]:
            out[str(D)] = round(best, 1)
    return out


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371008.8
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _gps_stream(points: list[tuple[float, float, float]]) -> tuple[list[float], list[float]]:
    """points: (t_seconds, lat, lon). 5-point moving average, then drop implausible jumps."""
    if len(points) < 2:
        return [], []
    k = 2
    sm = []
    for i in range(len(points)):
        win = points[max(0, i - k): i + k + 1]
        sm.append((points[i][0], sum(p[1] for p in win) / len(win), sum(p[2] for p in win) / len(win)))
    times, dists = [sm[0][0]], [0.0]
    for p0, p1 in zip(sm, sm[1:]):
        dt_ = p1[0] - p0[0]
        if dt_ <= 0:
            continue
        d = _haversine((p0[1], p0[2]), (p1[1], p1[2]))
        if d / dt_ > MAX_SPEED:
            d = 0.0
        times.append(p1[0])
        dists.append(dists[-1] + d)
    return times, dists


# ---------------------------------------------------------------- file parsers


# ---------------------------------------------------------------- streams for maps & charts

STREAM_ROUND = {"lat": 5, "lon": 5, "d": 1, "t": 1, "speed": 3, "ele": 1, "hr": 0, "cad": 0, "power": 0}


def make_streams(cols: dict[str, list], max_points: int = 900) -> dict:
    """Same shape as Garmin's streams (see integrations/garmin.streams_from_details): parallel lists
    t (s), d (m), hr, speed (m/s), ele, cad (steps/min), lat, lon, power; evenly downsampled."""
    t = cols.get("t") or []
    if len(t) < 2:
        return {}
    n = len(t)
    if not any(cols.get("speed") or []) and cols.get("d"):  # 5-sample window: 1 s GPS deltas are too noisy
        d, k = cols["d"], 5
        cols["speed"] = [(d[i] - d[max(0, i - k)]) / (t[i] - t[max(0, i - k)])
                         if i and d[i] is not None and d[max(0, i - k)] is not None and t[i] > t[max(0, i - k)] else None
                         for i in range(n)]
    out = {k: v for k, v in cols.items() if len(v) == n and any(x not in (None, 0) for x in v)}
    if n > max_points:
        keep = [round(j * (n - 1) / (max_points - 1)) for j in range(max_points)]
        out = {k: [v[j] for j in keep] for k, v in out.items()}
    return {k: [None if x is None else round(x, STREAM_ROUND.get(k, 1)) for x in v] for k, v in out.items()}


def gps_streams(rows: list[tuple]) -> dict:
    """rows: (t, lat, lon, ele, hr, cad) from GPX/TCX. Distance from smoothed positions (no point dropped,
    so every series stays aligned)."""
    if len(rows) < 2:
        return {}
    k = 2
    cols: dict[str, list] = {"t": [], "d": [], "lat": [], "lon": [], "ele": [], "hr": [], "cad": []}
    dist, prev = 0.0, None
    for i, r in enumerate(rows):
        win = rows[max(0, i - k): i + k + 1]
        p = (sum(w[1] for w in win) / len(win), sum(w[2] for w in win) / len(win))
        if prev is not None:
            step = _haversine(prev, p)
            if r[0] > rows[i - 1][0] and step / (r[0] - rows[i - 1][0]) <= MAX_SPEED:
                dist += step
        prev = p
        for key, v in zip(("t", "d", "lat", "lon", "ele", "hr", "cad"), (r[0], dist, r[1], r[2], r[3], r[4], r[5])):
            cols[key].append(v)
    return make_streams(cols)


def _local(ts: dt.datetime) -> dt.datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.UTC)
    return ts.astimezone().replace(tzinfo=None)


def _summary(start_utc: dt.datetime, times: list[float], dists: list[float], hrs: list[int], sport: str,
             moving_s: float | None = None, total_m: float | None = None, ascent: float | None = None,
             gps_only: bool = False, streams: dict | None = None) -> dict:
    start_local = _local(start_utc)
    distance = total_m if total_m else (dists[-1] - dists[0] if dists else 0)
    duration = moving_s if moving_s else (times[-1] - times[0] if times else 0)
    return {
        "date": start_local.date().isoformat(), "start_time": start_local.isoformat(sep=" ", timespec="seconds"),
        "sport": sport, "distance_m": round(distance, 1), "duration_s": round(duration, 1),
        "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None, "max_hr": max(hrs) if hrs else None,
        "elevation_gain": ascent, "best_efforts": best_efforts(times, dists), "gps_only": gps_only,
        **({"_streams": streams} if streams else {}),
    }


def parse_fit(data: bytes) -> dict | None:
    import fitdecode

    times, dists, hrs = [], [], []
    cols: dict[str, list] = {k: [] for k in ("t", "d", "hr", "speed", "ele", "cad", "lat", "lon", "power")}
    semi = 180 / 2 ** 31
    session: dict = {}
    t0: dt.datetime | None = None
    with fitdecode.FitReader(io.BytesIO(data), check_crc=fitdecode.CrcCheck.DISABLED) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "record":
                g = lambda k, f=frame: f.get_value(k, fallback=None)
                ts, d, hr = g("timestamp"), g("distance"), g("heart_rate")
                if hr:
                    hrs.append(int(hr))
                if ts is None or d is None:
                    continue
                t0 = t0 or ts
                sec = (ts - t0).total_seconds()
                if dists and (d < dists[-1] or sec <= times[-1]):
                    continue
                times.append(sec)
                dists.append(float(d))
                lat, lon, cad = g("position_lat"), g("position_long"), g("cadence")
                for k, v in (("t", sec), ("d", float(d)), ("hr", hr), ("speed", g("enhanced_speed") or g("speed")),
                             ("ele", g("enhanced_altitude") if g("enhanced_altitude") is not None else g("altitude")),
                             ("cad", cad * 2 if cad else None), ("power", g("power")),
                             ("lat", lat * semi if lat is not None else None), ("lon", lon * semi if lon is not None else None)):
                    cols[k].append(v)
            elif frame.name == "session" and not session:
                session = {f.name: f.value for f in frame.fields}
    if not times and not session:
        return None
    sport = str(session.get("sport") or "running").lower()
    start = session.get("start_time") or t0
    if not isinstance(start, dt.datetime):
        return None
    return _summary(start, times, dists, hrs, "running" if "run" in sport else sport,
                    moving_s=session.get("total_timer_time"), total_m=session.get("total_distance"),
                    ascent=session.get("total_ascent"), streams=make_streams(cols))


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _parse_iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))


def parse_gpx(data: bytes) -> dict | None:
    root = ET.fromstring(data)
    _strip_ns(root)
    pts, hrs, rows = [], [], []
    t0 = None
    for p in root.iter("trkpt"):
        tm = p.find("time")
        if tm is None or not tm.text:
            continue
        ts = _parse_iso(tm.text)
        t0 = t0 or ts
        sec, lat, lon = (ts - t0).total_seconds(), float(p.get("lat")), float(p.get("lon"))
        pts.append((sec, lat, lon))
        hr = p.find(".//hr")
        hrv = int(float(hr.text)) if hr is not None and hr.text else None
        if hrv:
            hrs.append(hrv)
        ele, cad = p.findtext("ele"), p.findtext(".//cad")
        rows.append((sec, lat, lon, float(ele) if ele else None, hrv, int(float(cad)) * 2 if cad else None))
    if len(pts) < 2 or t0 is None:
        return None
    typ = (root.findtext(".//trk/type") or "running").lower()
    times, dists = _gps_stream(pts)
    out = _summary(t0, times, dists, hrs, "running" if RUN_TYPES.search(typ) or typ in ("9", "running") else typ, gps_only=True,
                   streams=gps_streams(rows))
    name = (root.findtext(".//trk/name") or root.findtext("metadata/name") or "").strip()
    return {**out, "name": name[:80]} if name else out


def parse_tcx(data: bytes) -> dict | None:
    root = ET.fromstring(data.lstrip())
    _strip_ns(root)
    act = root.find(".//Activity")
    sport = (act.get("Sport") if act is not None else "Running") or "Running"
    pts, times, dists, hrs, rows = [], [], [], [], []
    t0 = None
    for tp in root.iter("Trackpoint"):
        tm = tp.findtext("Time")
        if not tm:
            continue
        ts = _parse_iso(tm)
        t0 = t0 or ts
        sec = (ts - t0).total_seconds()
        hr = tp.findtext("HeartRateBpm/Value")
        if hr:
            hrs.append(int(float(hr)))
        la, lo = tp.findtext("Position/LatitudeDegrees"), tp.findtext("Position/LongitudeDegrees")
        if la and lo:
            alt, cad = tp.findtext("AltitudeMeters"), tp.findtext(".//RunCadence") or tp.findtext("Cadence")
            rows.append((sec, float(la), float(lo), float(alt) if alt else None, int(float(hr)) if hr else None,
                         int(float(cad)) * 2 if cad else None))
        d = tp.findtext("DistanceMeters")
        if d is not None:
            if dists and (float(d) < dists[-1] or sec <= times[-1]):
                continue
            times.append(sec)
            dists.append(float(d))
        else:
            lat, lon = tp.findtext("Position/LatitudeDegrees"), tp.findtext("Position/LongitudeDegrees")
            if lat and lon:
                pts.append((sec, float(lat), float(lon)))
    if t0 is None:
        return None
    gps_only = not dists
    if gps_only:
        times, dists = _gps_stream(pts)
    total_m = sum(float(x.text) for x in root.iter("Lap") for x in [x.find("DistanceMeters")] if x is not None and x.text) or None
    moving = sum(float(x.text) for x in root.iter("Lap") for x in [x.find("TotalTimeSeconds")] if x is not None and x.text) or None
    return _summary(t0, times, dists, hrs, "running" if sport.lower().startswith("run") else sport.lower(),
                    moving_s=moving, total_m=total_m, gps_only=gps_only, streams=gps_streams(rows))


def parse_file(name: str, data: bytes) -> dict | None:
    low = name.lower()
    if low.endswith(".gz"):
        data = gzip.decompress(data)
        low = low[:-3]
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("archivo demasiado grande")
    if low.endswith(".fit"):
        return parse_fit(data)
    if low.endswith(".gpx"):
        return parse_gpx(data)
    if low.endswith(".tcx"):
        return parse_tcx(data)
    return None


# ---------------------------------------------------------------- Strava export


MONTHS = {**{m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])},
          **{m: i + 1 for i, m in enumerate(["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"])}, "sep": 9}


def parse_strava_date(s: str) -> dt.datetime | None:
    """'Jan 5, 2023, 7:12:33 AM' (UTC) or '5 ene 2023, 7:12:33' / ISO."""
    s = s.strip()
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=dt.UTC)
    except ValueError:
        pass
    m = re.match(r"([A-Za-zé]+)\.? (\d{1,2}), (\d{4}),? (\d{1,2}):(\d{2}):(\d{2})\s*([AP]M)?", s) or \
        re.match(r"(\d{1,2}) ([A-Za-zé]+)\.? (\d{4}),? (\d{1,2}):(\d{2}):(\d{2})\s*([AP]M)?", s)
    if not m:
        return None
    g = m.groups()
    if g[0].isdigit():
        day, mon = g[0], g[1]
    else:
        mon, day = g[0], g[1]
    month = MONTHS.get(mon.lower()[:4]) or MONTHS.get(mon.lower()[:3])
    if not month:
        return None
    h = int(g[3]) % 12 + (12 if g[6] == "PM" else 0) if g[6] else int(g[3])
    return dt.datetime(int(g[2]), month, int(day), h, int(g[4]), int(g[5]), tzinfo=dt.UTC)


def parse_strava_csv(text: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    head = rows[0]
    first: dict[str, int] = {}
    last: dict[str, int] = {}
    for i, h in enumerate(head):
        first.setdefault(h, i)
        last[h] = i
    out = []
    for r in rows[1:]:
        if len(r) < len(head) // 2:
            continue

        def get(col: str, which: dict = first, r: list[str] = r) -> str:
            i = which.get(col)
            return r[i].strip() if i is not None and i < len(r) else ""

        def num(v: str) -> float | None:
            try:
                return float(v.replace(",", "")) if v else None
            except ValueError:
                return None

        start = parse_strava_date(get("Activity Date"))
        if not start:
            continue
        dist = num(get("Distance", last))  # the second "Distance" column is metres
        if dist is not None and last.get("Distance") == first.get("Distance") and dist < 500:
            dist *= 1000  # single column in km
        moving = num(get("Moving Time")) or num(get("Elapsed Time", last))
        local = _local(start)
        out.append({
            "strava_id": get("Activity ID"), "name": get("Activity Name"), "type": get("Activity Type"),
            "date": local.date().isoformat(), "start_time": local.isoformat(sep=" ", timespec="seconds"),
            "distance_m": dist, "duration_s": moving, "avg_hr": num(get("Average Heart Rate")),
            "max_hr": num(get("Max Heart Rate")), "elevation_gain": num(get("Elevation Gain")),
            "filename": get("Filename"),
        })
    return out


# ---------------------------------------------------------------- archives


def iter_archive(source, depth: int = 0) -> Iterator[tuple[str, Callable[[], bytes]]]:
    """Yield (name, loader) for every member; nested zips (Garmin exports) are opened lazily.
    `source` is a path or bytes. Members are read only when their loader is called."""
    z = zipfile.ZipFile(source if isinstance(source, str) else io.BytesIO(source))
    for info in z.infolist():
        if info.is_dir() or info.file_size > MAX_FILE_BYTES * 8:
            continue
        if info.filename.lower().endswith(".zip") and depth < 2:
            yield from iter_archive(z.read(info), depth + 1)
        elif info.file_size <= MAX_FILE_BYTES:
            yield info.filename, (lambda z=z, info=info: z.read(info))


def activities_from_upload(name: str, source, progress=None) -> Iterator[dict]:
    """Yield normalized activities from one uploaded file (zip export or a single FIT/GPX/TCX).
    `source` is a path on disk or bytes."""
    if not name.lower().endswith(".zip"):
        data = source if isinstance(source, bytes) else open(source, "rb").read()
        a = parse_file(name, data)
        if progress:
            progress(1, 1)
        if a:
            yield {**a, "name": a.get("name") or name.rsplit("/", 1)[-1].split(".")[0], "source": "import",
                   "external_id": "file:" + hashlib.sha1(data).hexdigest()[:16]}
        return
    members = dict(iter_archive(source))
    csv_name = next((n for n in members if n.lower().endswith("activities.csv")), None)
    strava = parse_strava_csv(members[csv_name]().decode("utf-8-sig", "replace")) if csv_name else []
    by_file = {r["filename"]: r for r in strava if r["filename"]}
    files = [n for n in members if re.search(r"\.(fit|gpx|tcx)(\.gz)?$", n, re.I)]
    total = len(files) + sum(1 for r in strava if not r["filename"] or r["filename"] not in members)
    done = 0
    for n in files:
        row = by_file.get(n)
        done += 1
        if progress:
            progress(done, total)
        if row and row["type"] and not RUN_TYPES.search(row["type"]):
            continue  # Strava says it is not a run: skip parsing
        raw = members[n]()
        try:
            a = parse_file(n, raw)
        except Exception:  # noqa: BLE001 - a corrupt file must not stop the import
            a = None
        if not a:
            if row and RUN_TYPES.search(row["type"]) and row["distance_m"]:
                a = {k: row[k] for k in ("date", "start_time", "distance_m", "duration_s", "avg_hr", "max_hr", "elevation_gain")} | {"sport": "running", "best_efforts": {}}
            else:
                continue
        name_ = row["name"] if row else n.rsplit("/", 1)[-1].split(".")[0]
        ext = f"strava:{row['strava_id']}" if row and row["strava_id"] else "file:" + hashlib.sha1(raw).hexdigest()[:16]
        yield {**a, "name": name_, "source": "strava" if row else "import", "external_id": ext}
    # Strava rows without a track file (manual entries): whole-activity summary only
    for r in strava:
        if r["filename"] and r["filename"] in members:
            continue
        done += 1
        if progress:
            progress(done, total)
        if RUN_TYPES.search(r["type"] or "") and r["distance_m"] and r["duration_s"]:
            yield {k: r[k] for k in ("date", "start_time", "distance_m", "duration_s", "avg_hr", "max_hr", "elevation_gain")} | {
                "sport": "running", "best_efforts": {}, "name": r["name"], "source": "strava", "external_id": f"strava:{r['strava_id']}"}
