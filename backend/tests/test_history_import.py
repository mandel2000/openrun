import datetime as dt
import gzip
import io
import math
import os
import tempfile
import zipfile

os.environ.setdefault("OPENRUN_DB", os.path.join(tempfile.mkdtemp(), "hist.db"))

from sqlmodel import Session, select  # noqa: E402

from app import services as S  # noqa: E402
from app.db import Activity, engine, init_db  # noqa: E402
from app.integrations import history_import as H  # noqa: E402
from app.training import records as R  # noqa: E402


def stream(pace_s_km: float, km: float, fast: tuple[float, float, float] | None = None, step_s: float = 1.0):
    """Cumulative (times, dists) at constant pace, with an optional faster block (start_km, end_km, pace)."""
    t, d, times, dists = 0.0, 0.0, [0.0], [0.0]
    while d < km * 1000:
        p = fast[2] if fast and fast[0] * 1000 <= d < fast[1] * 1000 else pace_s_km
        d += 1000 / p * step_s
        t += step_s
        times.append(t)
        dists.append(d)
    return times, dists


def test_best_efforts_finds_fast_block():
    times, dists = stream(330, 12, fast=(4, 9, 270))  # 5 km block at 4:30/km inside easy running
    be = H.best_efforts(times, dists)
    assert abs(be["5000"] - 5 * 270) < 2
    assert abs(be["1000"] - 270) < 2
    assert 10000 * 0.27 < be["10000"] < 10000 * 0.33
    assert "21097" not in be


def test_best_efforts_rejects_impossible_gps():
    times, dists = stream(100, 2)  # 1:40/km is not human
    assert "1000" not in H.best_efforts(times, dists)


def track_points(km=6.0, pace=300, start=dt.datetime(2019, 5, 12, 8, 0, tzinfo=dt.timezone.utc), lat0=40.96, lon0=-5.66):
    """Points along a meridian line every 5 s (≈ GPS rate)."""
    pts, t, d = [], 0, 0.0
    while d <= km * 1000:
        lat = lat0 + d / 111195.0
        pts.append((start + dt.timedelta(seconds=t), lat, lon0, d))
        t += 5
        d += 5 * 1000 / pace
    return pts


def gpx(pts, typ="running"):
    body = "".join(f'<trkpt lat="{la:.7f}" lon="{lo:.7f}"><time>{t.isoformat().replace("+00:00", "Z")}</time>'
                   f'<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>150</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>'
                   for t, la, lo, _ in pts)
    return (f'<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1" '
            f'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"><trk><type>{typ}</type><trkseg>{body}</trkseg></trk></gpx>').encode()


def tcx(pts):
    tps = "".join(f"<Trackpoint><Time>{t.isoformat().replace('+00:00', 'Z')}</Time><DistanceMeters>{d:.1f}</DistanceMeters>"
                  f"<HeartRateBpm><Value>160</Value></HeartRateBpm></Trackpoint>" for t, _, _, d in pts)
    return (f'<?xml version="1.0"?><TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
            f'<Activities><Activity Sport="Running"><Lap><TotalTimeSeconds>{(pts[-1][0] - pts[0][0]).total_seconds()}</TotalTimeSeconds>'
            f'<DistanceMeters>{pts[-1][3]:.1f}</DistanceMeters><Track>{tps}</Track></Lap></Activity></Activities></TrainingCenterDatabase>').encode()


def test_parse_gpx_and_tcx():
    pts = track_points()
    g = H.parse_file("a.gpx", gpx(pts))
    assert g["sport"] == "running" and g["gps_only"] and g["avg_hr"] == 150
    assert abs(g["distance_m"] - pts[-1][3]) / pts[-1][3] < 0.01
    assert abs(g["best_efforts"]["5000"] - 1500) < 15
    t = H.parse_file("b.tcx.gz", gzip.compress(tcx(pts)))
    assert not t["gps_only"] and t["avg_hr"] == 160
    assert abs(t["best_efforts"]["5000"] - 1500) < 3
    assert t["date"] == pts[0][0].astimezone().date().isoformat()


def test_strava_dates():
    assert H.parse_strava_date("Jan 5, 2023, 7:12:33 PM") == dt.datetime(2023, 1, 5, 19, 12, 33, tzinfo=dt.timezone.utc)
    assert H.parse_strava_date("5 ene 2023, 7:12:33") == dt.datetime(2023, 1, 5, 7, 12, 33, tzinfo=dt.timezone.utc)
    assert H.parse_strava_date("2021-03-04 06:00:00").year == 2021


def strava_zip():
    pts = track_points(km=10.5, pace=280, start=dt.datetime(2019, 5, 12, 8, 0, tzinfo=dt.timezone.utc))
    head = ["Activity ID", "Activity Date", "Activity Name", "Activity Type", "Elapsed Time", "Distance", "Filename",
            "Elapsed Time", "Moving Time", "Distance", "Average Heart Rate"]
    rows = [
        ["111", "May 12, 2019, 8:00:00 AM", "Popular 10K", "Run", "2950", "10.50", "activities/111.gpx.gz", "2950", "2940", "10500.0", "165"],
        ["222", "Jun 1, 2019, 9:00:00 AM", "Ride", "Ride", "3600", "30.0", "activities/222.gpx", "3600", "3600", "30000.0", ""],
        ["333", "Apr 20, 2018, 7:00:00 PM", "Manual half", "Run", "6000", "21.10", "", "6000", "6000", "21100.0", ""],
    ]
    csv = "\n".join(",".join(f'"{c}"' for c in r) for r in [head, *rows])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("activities.csv", csv)
        z.writestr("activities/111.gpx.gz", gzip.compress(gpx(pts)))
        z.writestr("activities/222.gpx", gpx(track_points(km=30, pace=120), typ="cycling"))
    return buf.getvalue()


def test_strava_export_import_and_dedupe():
    init_db()
    with Session(engine) as s:
        # Garmin already has a run that duplicates nothing; and a "Garmin copy" of the 2018 half
        S.upsert_activity(s, {"external_id": "garmin:1", "date": "2018-04-20", "sport": "running", "distance_m": 21050, "duration_s": 6020})
        path = os.path.join(tempfile.mkdtemp(), "export.zip")
        open(path, "wb").write(strava_zip())
        stats = S.import_history(s, [("export_123.zip", path)])
        assert stats["imported"] == 1 and stats["duplicates"] == 1 and stats["with_efforts"] == 1
        a = s.exec(select(Activity).where(Activity.external_id == "strava:111")).one()
        assert a.data["name"] == "Popular 10K" and a.data["source"] == "strava"
        assert abs(a.data["best_efforts"]["10000"] - 2800) < 30
        # Re-import is idempotent
        assert S.import_history(s, [("export_123.zip", path)])["imported"] == 0
        mine = [r for r in s.exec(select(Activity)).all() if r.external_id.startswith("strava:") or r.external_id == "garmin:1"]  # DB is shared across test modules
        rec = R.records([{**r.data, "id": r.id, "date": r.date, "sport": r.sport} for r in mine], dt.date(2026, 10, 28))
        assert rec["all"]["10k"]["date"] == "2019-05-12" and rec["all"]["10k"]["approx"]  # GPS-only -> approx
        assert "10k" not in rec["1y"]


def test_uploaded_file_keeps_streams_for_map_and_charts():
    from sqlmodel import Session

    from app import services as S
    from app.db import Activity, engine, init_db

    init_db()
    start = dt.datetime.combine(dt.date.today() - dt.timedelta(days=3), dt.time(8, 0), tzinfo=dt.timezone.utc)
    g = H.parse_file("r.gpx", gpx(track_points(km=5, pace=300, start=start)))
    st = g["_streams"]
    assert {"t", "d", "lat", "lon", "hr", "speed"} <= set(st) and len(st["t"]) <= 900
    assert abs(st["d"][-1] - g["distance_m"]) < 0.05 * g["distance_m"]
    with Session(engine) as s:
        S.import_history(s, [("r.gpx", gpx(track_points(km=5, pace=300, start=start, lat0=41.5)))])
        act = s.exec(__import__("sqlmodel").select(Activity).where(Activity.date == start.date().isoformat())).all()[-1]
        d = S.activity_detail(s, act.id)
        assert d["has_streams"] and len(d["coords"]) > 100 and len(d["splits"]) == 5
        assert "_streams" not in act.data
