import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmtPace, fmtTime } from '../api'
import { Banner, Icon, Skeleton } from '../ui'

const RouteMap = lazy(() => import('./RouteMap'))

type Streams = Partial<Record<'t' | 'd' | 'hr' | 'speed' | 'gap' | 'ele' | 'cad' | 'power' | 'stride' | 'gct' | 'vo', (number | null)[]>>
type Split = { km: number; distance_m: number; time_s: number; pace_s: number | null; hr: number | null; cad: number | null; gain_m: number }
export type Detail = {
  activity: { id: number; name?: string; distance_m?: number; duration_s?: number; avg_hr?: number; elevation_gain?: number }
  has_streams: boolean; streams: Streams; coords: [number, number][]; splits: Split[]
  dynamics: { cadence: number | null; stride_cm: number | null; gct_ms: number | null; vertical_osc_cm: number | null; power_w: number | null }
}

const tooltipStyle = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text)' }

function tokens() {
  const cs = getComputedStyle(document.documentElement)
  const g = (k: string) => cs.getPropertyValue(k).trim()
  return { accent: g('--accent'), muted: g('--muted'), hr: g('--z5'), ele: g('--z0') }
}

// start and finish within ~150 m: one marker
const loop = (c: [number, number][]) => Math.hypot(c[0][0] - c[c.length - 1][0], (c[0][1] - c[c.length - 1][1]) * Math.cos(c[0][0] * Math.PI / 180)) < 0.00135

// rolling mean to tame GPS pace noise
function smooth(v: (number | null)[], w = 5) {
  return v.map((_, i) => {
    const win = v.slice(Math.max(0, i - w), i + w + 1).filter((x): x is number => x != null && x > 0)
    return win.length ? win.reduce((a, b) => a + b, 0) / win.length : null
  })
}

export default function ActivityDetail({ activityId }: { activityId: number }) {
  const [d, setD] = useState<Detail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  const c = useMemo(tokens, [])
  useEffect(() => {
    api.get<Detail>(`/api/activities/${activityId}/detail`).then(setD).catch((e) => setErr((e as Error).message))
  }, [activityId])
  const rows = useMemo(() => {
    if (!d?.streams.d) return []
    const s = d.streams
    const sp = smooth(s.speed ?? [], 6)
    return (s.d ?? []).map((dist, i) => ({
      i, km: dist != null ? +(dist / 1000).toFixed(2) : null,
      pace: sp[i] && sp[i]! > 1.2 ? Math.min(1000 / sp[i]!, 600) : null,
      hr: s.hr?.[i] || null, ele: s.ele?.[i] ?? null,
    })).filter((r) => r.km != null)
  }, [d])

  if (err) return <Banner tone="bad">{err}</Banner>
  if (!d) return <div className="stack"><Skeleton h={220} /><Skeleton h={120} /></div>
  if (!d.has_streams) return <Banner tone="info">Esta actividad no tiene datos detallados (importada de archivo o sin GPS).</Banner>

  const n = Math.max(1, rows.length - 1)
  const coordIdx = hover != null && d.coords.length ? Math.round((hover / n) * (d.coords.length - 1)) : null
  const onMove = (e: unknown) => { const i = (e as { activeTooltipIndex?: number }).activeTooltipIndex; setHover(i ?? null) }
  const dy = d.dynamics
  const paces = d.splits.map((x) => x.pace_s ?? 0).filter(Boolean)
  const best = paces.length ? Math.min(...paces) : 0
  const common = { syncId: `act-${activityId}`, margin: { top: 6, right: 8, left: 0, bottom: 0 }, onMouseMove: onMove, onMouseLeave: () => setHover(null) }
  const xAxis = <XAxis dataKey="km" type="number" domain={[0, 'dataMax']} stroke={c.muted} fontSize={11} tickLine={false} axisLine={false} unit=" km" tickCount={6} />

  return (
    <div className="stack">
      {d.coords.length > 1 && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <Suspense fallback={<Skeleton h={240} />}>
            <RouteMap coords={d.coords} height={240} highlight={coordIdx}
              marks={loop(d.coords) ? [{ at: d.coords[0], label: 'Salida y llegada', kind: 'start' }]
                : [{ at: d.coords[0], label: 'Salida', kind: 'start' }, { at: d.coords[d.coords.length - 1], label: 'Llegada', kind: 'finish' }]} />
          </Suspense>
        </div>
      )}
      <div className="mini-stats">
        {dy.cadence && <div><span className="micro">Cadencia</span><b>{Math.round(dy.cadence)} <small>ppm</small></b></div>}
        {dy.stride_cm && <div><span className="micro">Zancada</span><b>{(dy.stride_cm / 100).toFixed(2)} <small>m</small></b></div>}
        {dy.gct_ms && <div><span className="micro">Contacto suelo</span><b>{Math.round(dy.gct_ms)} <small>ms</small></b></div>}
        {dy.vertical_osc_cm && <div><span className="micro">Osc. vertical</span><b>{dy.vertical_osc_cm.toFixed(1)} <small>cm</small></b></div>}
        {dy.power_w && <div><span className="micro">Potencia</span><b>{Math.round(dy.power_w)} <small>W</small></b></div>}
      </div>
      <div>
        <div className="micro">Ritmo</div>
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={rows} {...common}>
            {xAxis}
            <YAxis stroke={c.muted} fontSize={11} tickLine={false} axisLine={false} width={44} reversed domain={['dataMin - 10', 'dataMax + 10']} tickFormatter={(v) => fmtPace(v)} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${fmtPace(+v)}/km`, 'Ritmo']} labelFormatter={(l) => `km ${l}`} />
            <Line dataKey="pace" stroke={c.accent} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {d.streams.hr && (
        <div>
          <div className="micro">Frecuencia cardiaca</div>
          <ResponsiveContainer width="100%" height={110}>
            <LineChart data={rows} {...common}>
              {xAxis}
              <YAxis stroke={c.muted} fontSize={11} tickLine={false} axisLine={false} width={44} domain={['dataMin - 5', 'dataMax + 5']} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v} ppm`, 'FC']} labelFormatter={(l) => `km ${l}`} />
              <Line dataKey="hr" stroke={c.hr} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {d.streams.ele && (
        <div>
          <div className="micro">Altitud</div>
          <ResponsiveContainer width="100%" height={90}>
            <AreaChart data={rows} {...common}>
              {xAxis}
              <YAxis stroke={c.muted} fontSize={11} tickLine={false} axisLine={false} width={44} domain={['dataMin - 5', 'dataMax + 5']} tickFormatter={(v) => `${Math.round(v)}`} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${Math.round(+v)} m`, 'Altitud']} labelFormatter={(l) => `km ${l}`} />
              <Area dataKey="ele" stroke={c.ele} fill={c.ele} fillOpacity={0.2} strokeWidth={1.5} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      {d.splits.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Km</th><th className="n">Ritmo</th><th></th><th className="n">FC</th><th className="n hide-sm">Cad.</th><th className="n">Desn.</th></tr></thead>
            <tbody>
              {d.splits.map((x) => (
                <tr key={x.km}>
                  <td className="num">{x.distance_m < 950 ? `${(x.distance_m / 1000).toFixed(2)}` : x.km}</td>
                  <td className="n">{fmtPace(x.pace_s)}</td>
                  <td style={{ width: '35%' }}><div className="progress"><span style={{ width: `${x.pace_s && best ? Math.max(8, 100 - (x.pace_s - best) * 1.5) : 0}%` }} /></div></td>
                  <td className="n">{x.hr ?? ''}</td>
                  <td className="n hide-sm">{x.cad ?? ''}</td>
                  <td className="n">{x.gain_m ? `+${x.gain_m}` : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="small muted" style={{ margin: 0 }}>
        <Icon name="activity" size={13} /> {fmtTime(d.activity.duration_s)} · mapa © OpenStreetMap
      </p>
    </div>
  )
}
