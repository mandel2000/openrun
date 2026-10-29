"""Race-day strategy: per-km target paces on the real course profile, heat, fuelling.

Pacing by even effort, not even pace. On hilly courses the fastest finish comes from keeping metabolic
power roughly constant: slower on the climbs, faster on the descents (Minetti et al. 2002 energy
cost of running vs gradient; even-effort pacing beats even pace on undulating courses, Townshend
et al. 2010). Minetti's lab costs overstate the effect at race speed (HR-based grade-adjusted
pace models such as Strava's 2017 GAP show a smaller uphill penalty), and the downhill saving is
not fully usable (eccentric load, foot speed): we take 80 % of the uphill cost and 50 % of the
downhill saving; grades are clipped to ±12-15 %.

Start: the first 1-2 km a little conservative (crowded start, lactate build-up of a fast start
costs more later; Abbiss & Laursen 2008). The total stays on target: the rest is a hair faster.
Heat: Hadley rule (see heat.py). Fuelling: 30-60 g CHO/h for 1-2.5 h efforts and mouth rinse/gel
before 75 min (Jeukendrup 2014, ACSM 2016); carb loading 7-10 g/kg/day 24-36 h before races
> 90 min (Burke 2011).
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ..i18n import N_, _

# ---------------------------------------------------------------- course profiles


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def parse_track(filename: str, content: bytes) -> list[tuple[float, float, float | None]]:
    """(lat, lon, ele) points from GPX (trk/rte), TCX or KML LineString."""
    root = ET.fromstring(content)
    pts: list[tuple[float, float, float | None]] = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("trkpt", "rtept") and el.get("lat"):
            ele = next((c.text for c in el if c.tag.rsplit("}", 1)[-1] == "ele"), None)
            pts.append((float(el.get("lat")), float(el.get("lon")), float(ele) if ele else None))
        elif tag == "Trackpoint":
            lat = lon = ele = None
            for c in el.iter():
                t = c.tag.rsplit("}", 1)[-1]
                if t == "LatitudeDegrees":
                    lat = float(c.text)
                elif t == "LongitudeDegrees":
                    lon = float(c.text)
                elif t == "AltitudeMeters":
                    ele = float(c.text)
            if lat is not None and lon is not None:
                pts.append((lat, lon, ele))
        elif tag == "coordinates" and el.text and not pts:
            for tok in el.text.split():
                parts = tok.split(",")
                if len(parts) >= 2:
                    pts.append((float(parts[1]), float(parts[0]), float(parts[2]) if len(parts) > 2 and float(parts[2]) != 0 else None))
    if len(pts) < 2:
        raise ValueError(_("{file}: no course found (trk/rte/LineString)", file=filename))
    return pts


def fill_elevation(pts: list[tuple[float, float, float | None]]) -> list[tuple[float, float, float | None]]:
    """Tracks without altitude (KML, drawn routes): look it up in Open-Meteo's free elevation API
    (Copernicus DEM 90 m), sampling every ~50 m."""
    if sum(1 for p in pts if p[2] is not None) > len(pts) * 0.8:
        return pts
    import httpx

    keep = [0]
    acc = 0.0
    for i in range(1, len(pts)):
        acc += _haversine(pts[i - 1][:2], pts[i][:2])
        if acc >= 50 or i == len(pts) - 1:
            keep.append(i)
            acc = 0.0
    sample = [pts[i] for i in keep]
    eles: list[float] = []
    for j in range(0, len(sample), 100):
        chunk = sample[j:j + 100]
        r = httpx.get("https://api.open-meteo.com/v1/elevation", timeout=20, params={
            "latitude": ",".join(f"{p[0]:.5f}" for p in chunk), "longitude": ",".join(f"{p[1]:.5f}" for p in chunk)})
        r.raise_for_status()
        eles += r.json()["elevation"]
    return [(p[0], p[1], e) for p, e in zip(sample, eles)]


def profile_from_track(pts: list[tuple[float, float, float | None]]) -> list[list[float]]:
    """[[distance_m, elevation_m], ...] every ~100 m, elevation smoothed (GPS altitude is noisy)."""
    d = 0.0
    raw: list[tuple[float, float]] = []
    last_ele = next((p[2] for p in pts if p[2] is not None), 0.0)
    for i, p in enumerate(pts):
        if i:
            d += _haversine(pts[i - 1][:2], p[:2])
        last_ele = p[2] if p[2] is not None else last_ele
        raw.append((d, last_ele))
    out: list[list[float]] = []
    j = 0
    x = 0.0
    while x <= d:
        while j < len(raw) - 2 and raw[j + 1][0] < x:
            j += 1
        (d0, e0), (d1, e1) = raw[j], raw[min(j + 1, len(raw) - 1)]
        e = e0 if d1 <= d0 else e0 + (e1 - e0) * (x - d0) / (d1 - d0)
        out.append([round(x, 1), e])
        x += 100.0
    if out[-1][0] < d:
        out.append([round(d, 1), raw[-1][1]])
    sm = [p[1] for p in out]  # 300 m centred moving average
    for i in range(len(out)):
        win = sm[max(0, i - 1):i + 2]
        out[i][1] = round(sum(win) / len(win), 1)
    return out


def course_coords(pts: list[tuple[float, float, float | None]], max_n: int = 400) -> list[list[float]]:
    step = max(1, len(pts) // max_n)
    out = [[round(p[0], 5), round(p[1], 5)] for p in pts[::step]]
    if out[-1] != [round(pts[-1][0], 5), round(pts[-1][1], 5)]:
        out.append([round(pts[-1][0], 5), round(pts[-1][1], 5)])
    return out


# Approximate Behobia-San Sebastián profile from the organiser's km-by-km description (192 m D+;
# Irun / Arretxe, Gaintxurizketa 2 km at ~3 %, Capuchinos 450 m at 5 %, Miracruz 1.5 km at 3 %).
# Upload the official GPX for the exact profile.
_BEHOBIA = [(0, 5), (1000, 8), (2000, 25), (3000, 45), (3400, 55), (4000, 45), (5000, 30), (5600, 36), (6000, 42),
            (7000, 70), (8000, 98), (9000, 70), (10000, 42), (11000, 16), (12000, 12), (12600, 14), (13050, 36),
            (13600, 30), (14000, 18), (15000, 12), (16000, 15), (17000, 55), (18000, 24), (18800, 8), (19200, 12),
            (20000, 6)]
_BEHOBIA_NOTES = {
    2: N_("Irun: gentle climb through the crowd. Don't get carried away."),
    3: N_("Steep climb out of Irun (Ventas / Arretxe). Run by effort, not by pace."),
    5: N_("Downhill: recover and loosen up, without braking."),
    7: N_("Gaintxurizketa (~2 km at 3%). High cadence, short stride, steady effort."),
    8: N_("Top of Gaintxurizketa: 200 m after the summit, back to your pace."),
    9: N_("Long descent to Errenteria: use it relaxed, let it carry you."),
    12: N_("Flat through Errenteria: a good stretch to settle the pace. Watch the speed bumps."),
    13: N_("Capuchinos: 450 m at 5%, the hardest part. Active arms, short and quick."),
    16: N_("Trintxerpe / Herrera: get ready for Miracruz."),
    17: N_("Alto de Miracruz (~1.5 km at 3%). Whatever you saved, spend it here."),
    18: N_("Downhill through Ategorrieta: now you can push."),
    20: N_("Zurriola and Boulevard: empty the tank."),
}


def _interp(points: list[tuple[float, float]], total: float) -> list[list[float]]:
    out = []
    x = 0.0
    j = 0
    while x <= total + 1e-6:
        while j < len(points) - 2 and points[j + 1][0] < x:
            j += 1
        (d0, e0), (d1, e1) = points[j], points[j + 1]
        out.append([x, round(e0 + (e1 - e0) * (x - d0) / (d1 - d0), 1)])
        x += 100.0
    return out


BUILTIN = {
    "behobia": {"name": "Behobia-San Sebastián", "distance_m": 20000, "approx": True,
                "profile": _interp(_BEHOBIA, 20000), "notes": _BEHOBIA_NOTES, "start": [43.3373, -1.7581],
                "start_time": "10:30"},
}


def builtin_for(name: str) -> dict | None:
    n = (name or "").lower()
    return BUILTIN["behobia"] if "behobia" in n else None


def flat_profile(distance_m: float) -> list[list[float]]:
    return [[min(x * 100.0, distance_m), 0.0] for x in range(int(distance_m // 100) + 1)] + \
        ([[distance_m, 0.0]] if distance_m % 100 else [])


# ---------------------------------------------------------------- pacing


def minetti_cost(g: float) -> float:
    """Energy cost of running (J/kg/m) at gradient g (fraction), Minetti et al. 2002."""
    return 155.4 * g**5 - 30.4 * g**4 - 43.3 * g**3 + 46.3 * g**2 + 19.5 * g + 3.6


def effort_factor(g: float) -> float:
    """Time multiplier vs flat for equal effort: 80 % of the uphill cost, half the downhill saving."""
    g = max(-0.12, min(0.15, g))
    f = minetti_cost(g) / minetti_cost(0.0)
    return 1 + 0.8 * (f - 1) if g >= 0 else 1 - 0.5 * (1 - f)


def course_factor(profile: list[list[float]]) -> float:
    """Course time / flat time at equal effort (1.03 = this course costs ~3 % vs flat)."""
    tot = num = 0.0
    for (d0, e0), (d1, e1) in zip(profile, profile[1:]):
        L = d1 - d0
        if L <= 0:
            continue
        tot += L
        num += L * effort_factor((e1 - e0) / L)
    return num / tot if tot else 1.0


def gain_loss(profile: list[list[float]]) -> tuple[float, float]:
    up = sum(max(0.0, b[1] - a[1]) for a, b in zip(profile, profile[1:]))
    down = sum(max(0.0, a[1] - b[1]) for a, b in zip(profile, profile[1:]))
    return round(up), round(down)


START_EASE = {0: 0.02, 1: 0.008}  # km index -> extra % slower (crowded start, avoid the fast-start penalty)


def pace_plan(profile: list[list[float]], target_s: float, notes: dict | None = None) -> dict:
    """Per-km splits for an even-effort race finishing in target_s on this profile."""
    distance = profile[-1][0]
    segs = []
    for (d0, e0), (d1, e1) in zip(profile, profile[1:]):
        L = d1 - d0
        if L <= 0:
            continue
        g = (e1 - e0) / L
        km = int((d0 + 1e-6) // 1000)
        segs.append((d0, d1, L, g, effort_factor(g) * (1 + START_EASE.get(km, 0.0))))
    k = target_s / sum(L * w for _, _, L, _, w in segs)
    kms: dict[int, dict] = {}
    for d0, _d1, L, g, w in segs:
        km = int((d0 + 1e-6) // 1000)
        r = kms.setdefault(km, {"km": km + 1, "from_m": km * 1000, "to_m": min((km + 1) * 1000, distance), "time": 0.0,
                                "up": 0.0, "down": 0.0, "max_grade": 0.0})
        r["time"] += L * w * k
        r["up"] += max(0.0, g * L)
        r["down"] += max(0.0, -g * L)
        r["max_grade"] = max(r["max_grade"], g * 100, key=abs)
    out = []
    cum = 0.0
    flat_pace = k * 1000  # s/km on the flat at this effort (before start ease)
    for km in sorted(kms):
        r = kms[km]
        length = r["to_m"] - r["from_m"]
        cum += r["time"]
        net = r["up"] - r["down"]
        out.append({"km": r["km"], "distance_m": round(length), "pace_s": round(r["time"] / length * 1000, 1),
                    "split_s": round(r["time"], 1), "cum_s": round(cum, 1), "gain_m": round(r["up"]), "loss_m": round(r["down"]),
                    "grade_pct": round(net / length * 100, 1), "max_grade_pct": round(r["max_grade"], 1),
                    "terrain": "subida" if net / length > 0.012 else "bajada" if net / length < -0.012 else "llano",
                    "note": _n((notes or {}).get(r["km"]) or (notes or {}).get(str(r["km"])))})
    half = next((x["cum_s"] for x in out if x["km"] * 1000 >= distance / 2), None)
    return {"kms": out, "total_s": round(cum), "avg_pace_s": round(cum / distance * 1000, 1), "flat_pace_s": round(flat_pace, 1),
            "half_s": half, "course_factor": round(course_factor(profile), 4)}


TERRAIN = {"subida": N_("uphill"), "bajada": N_("downhill"), "llano": N_("flat")}  # ids stay Spanish (API data)


def _n(note: str | None) -> str | None:
    return _(note) if note else note


def fuelling(total_s: float, weight_kg: float | None, distance_m: float) -> list[str]:
    h = total_s / 3600
    tips = []
    if h >= 1.5:
        tips.append(_("Carb loading: 7-10 g/kg the day before{grams}: rice, pasta, bread, fruit; little fibre and fat.",
                      grams=f" (≈{round(weight_kg * 8)} g)" if weight_kg else ""))
    else:
        tips.append(_("Normal carb-rich dinner the night before; no specific loading needed under 90 min."))
    tips.append(_("Breakfast 2.5-3 h before: 1-2 g/kg of easy carbs (white bread with honey or jam, banana). Nothing new on race day."))
    if h >= 1.0:
        n = 2 if h >= 1.4 else 1
        at = [round(distance_m / 1000 * f) for f in ((0.33, 0.66) if n == 2 else (0.45,))]
        tips.append(_("During: {n} gel(s) (≈{g} g of carbs, 30-60 g/h) around km {kms}, always with water. Try them first in a long run.",
                      n=n, g=25 * n, kms=f" {_('and')} ".join(map(str, at))))
    else:
        tips.append(_("During: under an hour, rinsing your mouth with a sports drink is enough; water if it's hot."))
    tips.append(_("Sip at the aid stations according to thirst; no need to drink at every one."))
    return tips


def strategy_tips(total_s: float, cf: float, heat_pct: float) -> list[str]:
    tips = [
        _("Run the hills by effort: your pace goes up, your effort doesn't. Make up lost time on the next descent, not on the climb."),
        _("First km a bit slower than your body wants: starts are narrow and crowded; going out fast costs you at the end."),
        _("Watch the average per section, not the instant pace: GPS fails in tunnels and narrow streets. Use the official km markers."),
    ]
    if cf > 1.01:
        tips.append(_("This course costs ≈{pct}% more than a flat one: your average pace will be slower than on the flat at the same fitness. That's normal.", pct=f"{(cf - 1) * 100:.1f}"))
    if heat_pct > 0:
        tips.append(_("Heat forecast: target slowed by {pct}%. Wet your neck and forearms at the aid stations.", pct=f"{heat_pct:.1f}"))
    return tips


def watch_steps(kms: list[dict], tolerance_s: float = 6.0) -> list[dict]:
    """Garmin steps: one distance step per km (pace window ±tolerance) — the watch alerts per km."""
    steps = []
    for x in kms:
        steps.append({"kind": "run", "duration_type": "distance", "duration_value": x["distance_m"],
                      "pace_slow": round(x["pace_s"] + tolerance_s, 1), "pace_fast": round(x["pace_s"] - tolerance_s, 1),
                      "zone": None, "note": f"Km {x['km']}: {x['note'] or _(TERRAIN[x['terrain']])}"[:120]})
    return steps
