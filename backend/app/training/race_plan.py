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
        raise ValueError(f"{filename}: no se encontró ningún recorrido (trk/rte/LineString)")
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
    2: "Irun: subida suave entre el público. No te dejes llevar.",
    3: "Repecho fuerte de salida de Irun (Ventas / Arretxe). Por esfuerzo, no por ritmo.",
    5: "Bajada: recupera y ve soltando, sin frenar.",
    7: "Gaintxurizketa (~2 km al 3 %). Cadencia alta, zancada corta, esfuerzo constante.",
    8: "Coronas Gaintxurizketa: los 200 m tras la cima, vuelve a tu ritmo.",
    9: "Bajada larga a Errenteria: aprovéchala relajado, deja que te lleve.",
    12: "Llano de Errenteria: buen tramo para asentar ritmo. Ojo con los pasos elevados.",
    13: "Capuchinos: 450 m al 5 %, lo más duro. Brazos activos, corto y rápido.",
    16: "Trintxerpe / Herrera: prepárate para Miracruz.",
    17: "Alto de Miracruz (~1.5 km al 3 %). Lo que guardaste, se gasta aquí.",
    18: "Bajada por Ategorrieta: ya puedes apretar.",
    20: "Zurriola y Boulevard: a vaciarte.",
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
    "behobia": {"name": "Behobia-San Sebastián (perfil aproximado)", "distance_m": 20000, "approx": True,
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
                    "note": (notes or {}).get(r["km"]) or (notes or {}).get(str(r["km"]))})
    half = next((x["cum_s"] for x in out if x["km"] * 1000 >= distance / 2), None)
    return {"kms": out, "total_s": round(cum), "avg_pace_s": round(cum / distance * 1000, 1), "flat_pace_s": round(flat_pace, 1),
            "half_s": half, "course_factor": round(course_factor(profile), 4)}


def fuelling(total_s: float, weight_kg: float | None, distance_m: float) -> list[str]:
    h = total_s / 3600
    tips = []
    if h >= 1.5:
        tips.append(f"Carga de hidratos: 7-10 g/kg el día anterior{f' (≈{round(weight_kg * 8)} g)' if weight_kg else ''}: arroz, pasta, pan, fruta; poca fibra y grasa.")
    else:
        tips.append("Cena normal rica en hidratos la víspera; no hace falta carga específica para menos de 90 min.")
    tips.append("Desayuno 2,5-3 h antes: 1-2 g/kg de hidratos fáciles (pan blanco con miel o mermelada, plátano). Nada nuevo el día de carrera.")
    if h >= 1.0:
        n = 2 if h >= 1.4 else 1
        at = [round(distance_m / 1000 * f) for f in ((0.33, 0.66) if n == 2 else (0.45,))]
        tips.append(f"Durante: {n} gel{'es' if n > 1 else ''} (≈{25 * n} g de hidratos, 30-60 g/h) hacia los km {' y '.join(map(str, at))}, siempre con agua. Pruébalos antes en un entreno largo.")
    else:
        tips.append("Durante: con menos de una hora basta enjuagarse la boca con bebida isotónica; agua si hace calor.")
    tips.append("Bebe a sorbos en los avituallamientos según la sed; no hace falta beber en todos.")
    return tips


def strategy_tips(total_s: float, cf: float, heat_pct: float) -> list[str]:
    tips = [
        "Corre por esfuerzo en las cuestas: tu ritmo sube, tu esfuerzo no. Recupera lo perdido en la bajada siguiente, no en la subida.",
        "Primer km algo más lento de lo que el cuerpo pide: la salida es estrecha y llena de gente; salir rápido se paga al final.",
        "Mira la media por tramos, no el ritmo instantáneo: el GPS falla en túneles y calles estrechas. Usa las marcas de km oficiales.",
    ]
    if cf > 1.01:
        tips.append(f"Este recorrido cuesta ≈{(cf - 1) * 100:.1f} % más que uno llano: tu ritmo medio será más lento que en un llano a igual forma. Es normal.")
    if heat_pct > 0:
        tips.append(f"Calor previsto: objetivo ralentizado un {heat_pct:.1f} %. Mójate nuca y antebrazos en los avituallamientos.")
    return tips


def watch_steps(kms: list[dict], tolerance_s: float = 6.0) -> list[dict]:
    """Garmin steps: one distance step per km (pace window ±tolerance) — the watch alerts per km."""
    steps = []
    for x in kms:
        steps.append({"kind": "run", "duration_type": "distance", "duration_value": x["distance_m"],
                      "pace_slow": round(x["pace_s"] + tolerance_s, 1), "pace_fast": round(x["pace_s"] - tolerance_s, 1),
                      "zone": None, "note": f"Km {x['km']}: {x['note'] or x['terrain']}"[:120]})
    return steps
