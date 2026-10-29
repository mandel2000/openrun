import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'
import { t } from '../i18n'

// Route on an OpenStreetMap base map. `coords` are [lat, lon]; `marks` are labelled points
// (km markers, start/finish). `highlight` is an index into coords drawn as a moving dot.
export type Mark = { at: [number, number]; label: string; kind?: 'start' | 'finish' | 'km' }

export default function RouteMap({ coords, marks = [], highlight, height = 280 }: {
  coords: [number, number][]; marks?: Mark[]; highlight?: number | null; height?: number
}) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const dot = useRef<L.CircleMarker | null>(null)

  useEffect(() => {
    if (!el.current || coords.length < 2) return
    const m = L.map(el.current, { zoomControl: true, attributionControl: true, scrollWheelZoom: false })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(m)
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#0E9F8E'
    const line = L.polyline(coords, { color: accent, weight: 4, opacity: 0.9 }).addTo(m)
    for (const k of marks) {
      const cls = k.kind === 'km' ? 'map-km' : 'map-pin'
      L.marker(k.at, { icon: L.divIcon({ className: cls, html: `<span>${k.label}</span>`, iconSize: undefined }), keyboard: false }).addTo(m)
    }
    m.fitBounds(line.getBounds(), { padding: [16, 16] })
    map.current = m
    return () => { m.remove(); map.current = null; dot.current = null }
  }, [coords, marks])

  useEffect(() => {
    const m = map.current
    if (!m) return
    if (highlight == null || !coords[highlight]) { dot.current?.remove(); dot.current = null; return }
    if (!dot.current) dot.current = L.circleMarker(coords[highlight], { radius: 7, color: '#fff', weight: 2, fillColor: '#111', fillOpacity: 1 }).addTo(m)
    else dot.current.setLatLng(coords[highlight])
  }, [highlight, coords])

  if (coords.length < 2) return null
  return <div ref={el} className="routemap" style={{ height }} role="img" aria-label={t('Route map')} />
}
