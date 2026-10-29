"""Orycron Sport race calendar (Salamanca and nearby). No public API: the public listing and event
pages are parsed from HTML. Requests are few (one listing + one page per opened event), cached for
12 h, and identify the client. robots.txt allows general access (Content-Signal: search=yes).
"""

from __future__ import annotations

import datetime as dt
import html
import re
import time

import httpx

from ..i18n import _

BASE = "https://www.orycronsport.com"
UA = "OpenRun/0.1 (personal training app; +https://github.com/)"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"])}
NOT_RUNNING = re.compile(r"\b(btt|bici|cicloturista|ciclista|mtb|marcha|caminantes|senderista|nataci|duatl|triatl|patin)", re.I)
TTL_S = 12 * 3600
_cache: dict[str, tuple[float, object]] = {}


def _get(path: str) -> str:
    hit = _cache.get(path)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]  # type: ignore[return-value]
    r = httpx.get(BASE + path, headers={"User-Agent": UA}, follow_redirects=True, timeout=15)
    r.raise_for_status()
    _cache[path] = (time.time(), r.text)
    return r.text


def _parse_es_date(text: str) -> str | None:
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", text.lower())
    if not m or m.group(2) not in MONTHS:
        return None
    return dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))).isoformat()


def parse_listing(page: str) -> list[dict]:
    out = []
    for m in re.finditer(r'href="/competiciones/(\d+)"[^>]*>.*?<span class="spanEstado">(.*?)</span>'
                         r'<strong>(.*?)</strong><span class="spanFecha">(.*?)</span>', page, re.S):
        eid, status, name, date_txt = m.groups()
        name = html.unescape(name).strip()
        out.append({"external_id": f"orycron:{eid}", "name": name, "date": _parse_es_date(html.unescape(date_txt)),
                    "status": html.unescape(status).strip(), "url": f"{BASE}/competiciones/{eid}",
                    "running": not NOT_RUNNING.search(name), "source": "orycron"})
    return out


def _text(page: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return re.sub(r"\n\s*\n+", "\n", t)


def parse_distances_km(text: str) -> list[float]:
    """Distances mentioned as '11,8km', '10 km', '21.097 m'..."""
    kms = []
    for num, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*(km|kms|kilómetros|metros|m)\b", text, re.I):
        v = float(num.replace(",", "."))
        if unit.lower().startswith("k"):
            pass
        elif v >= 400:  # metres
            v = v / 1000
        else:
            continue
        if 0.4 <= v <= 120 and v not in kms:
            kms.append(round(v, 3))
    if re.search(r"media\s+marat[oó]n", text, re.I) and 21.097 not in kms:
        kms.append(21.097)
    return kms


def parse_event(page: str) -> dict:
    t = _text(page)

    def field(label: str) -> str | None:
        m = re.search(rf"\n{label}:\s*\n(.+)", t)
        return m.group(1).strip() if m else None

    recorrido = field("Recorrido") or ""
    kms = parse_distances_km(recorrido) or parse_distances_km(t)
    return {"date": _parse_es_date(field("Día") or ""), "time": field("Hora"), "location": field("Lugar"),
            "price": field("Precio"), "route": recorrido or None, "distances_km": kms}


def upcoming(include_non_running: bool = False) -> list[dict]:
    items = parse_listing(_get("/competiciones/?proximas=1"))
    return [i for i in items if include_non_running or i["running"]]


def event(eid: str) -> dict:
    eid = eid.split(":")[-1]
    if not eid.isdigit():
        raise ValueError(_("invalid race id"))
    return {"external_id": f"orycron:{eid}", "url": f"{BASE}/competiciones/{eid}", **parse_event(_get(f"/competiciones/{eid}"))}
