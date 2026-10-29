import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Area, AreaChart, Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmtDate, fmtPace, fmtTime, type Race } from '../api'
import { Banner, Icon, Segmented, Skeleton } from '../ui'
import type { Mark } from './RouteMap'
import { t } from '../i18n'

const RouteMap = lazy(() => import('./RouteMap'))

type Km = { km: number; distance_m: number; pace_s: number; split_s: number; cum_s: number; gain_m: number; loss_m: number
  grade_pct: number; max_grade_pct: number; terrain: 'subida' | 'bajada' | 'llano'; note: string | null }
export type Strategy = {
  race: Race; mode: string; start_time: string; target_s: number; total_s: number; avg_pace_s: number; flat_pace_s: number; half_s: number | null
  course: { name: string; approx: boolean; flat: boolean; builtin: boolean; distance_m: number; gain_m: number; loss_m: number
    profile: [number, number][]; coords: [number, number][] | null; factor: number }
  prediction: { vdot: number | null; flat_s: number | null; course_s: number | null; modes: Record<string, number>; goal_s: number | null }
  weather: { temp: number; dew: number; rain_pct: number | null; wind_kmh: number | null; hour: number; days_ahead: number; slowdown_pct?: number } | null
  heat_pct: number; kms: Km[]; fuel: string[]; tips: string[]
}

const MODE_LABEL: Record<string, string> = { conservative: t('Safe'), realistic: t('Realistic'), ambitious: t('Ambitious'), custom: t('My time') }
const TERRAIN_COLOR: Record<string, string> = { subida: 'var(--z4)', bajada: 'var(--z1)', llano: 'var(--z2)' }
// terrain ids come from the API in Spanish; labels are translated here
const TERRAIN_LABEL: Record<string, string> = { subida: t('uphill'), bajada: t('downhill'), llano: t('flat') }

function useTokens() {
  const read = () => {
    const cs = getComputedStyle(document.documentElement)
    const g = (k: string) => cs.getPropertyValue(k).trim()
    return { accent: g('--accent'), muted: g('--muted'), border: g('--border'), up: g('--z4'), down: g('--z1'), flat: g('--z2'), soft: g('--accent-soft') }
  }
  const [t, setT] = useState(read)
  useEffect(() => {
    const on = () => setT(read())
    const mo = new MutationObserver(on)
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', on)
    return () => { mo.disconnect(); mq.removeEventListener('change', on) }
  }, [])
  return t
}

const tooltipStyle = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text)' }

function CourseCard({ st, onCourse }: { st: Strategy; onCourse: (s: Strategy) => void }) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const run = async (fn: () => Promise<Strategy>) => {
    setBusy(true)
    setErr(null)
    try { onCourse(await fn()) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <details className="card" open={st.course.flat || st.course.approx}>
      <summary className="row" style={{ cursor: 'pointer' }}>
        <Icon name="upload" size={18} /><b className="grow">{t('Course')}: {st.course.name}</b>
        {st.course.approx && <span className="chip chip-warn">{t('approximate')}</span>}
        {st.course.flat && <span className="chip chip-warn">{t('no profile')}</span>}
      </summary>
      <p className="small text-2">
        {st.course.flat ? t('No profile: computed as if it were flat.') + ' ' : st.course.approx ? t('Profile rebuilt from the official km-by-km description.') + ' ' : ''}
        {t('Upload the official GPX (or a TCX/KML, or the organiser’s .zip) for the exact profile. If the file has no elevation, it comes from a terrain model.')}
      </p>
      <div className="row">
        <input ref={file} type="file" accept=".gpx,.tcx,.kml,.zip" hidden onChange={(e) => {
          const f = e.target.files?.[0]
          if (!f) return
          const fd = new FormData()
          fd.append('file', f)
          run(() => api.post<Strategy>(`/api/races/${st.race.id}/course`, fd))
          e.target.value = ''
        }} />
        <button className="btn btn-sm" disabled={busy} onClick={() => file.current?.click()}><Icon name="upload" size={16} />{t('Upload GPX')}</button>
        {st.race.has_course && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => run(() => api.del<Strategy>(`/api/races/${st.race.id}/course`))}>{t('Remove GPX')}</button>}
      </div>
      <div className="row" style={{ marginTop: 8, alignItems: 'flex-end' }}>
        <label className="field grow">{t('or paste the GPX link')}<input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/course.gpx" inputMode="url" /></label>
        <button className="btn btn-sm" disabled={busy || !url.startsWith('https://')} onClick={() => run(() => api.post<Strategy>(`/api/races/${st.race.id}/course/url`, { url }))}>{t('Import')}</button>
      </div>
      {busy && <p className="small muted">{t('Processing course…')}</p>}
      {err && <div style={{ marginTop: 8 }}><Banner tone="bad">{err}</Banner></div>}
    </details>
  )
}

export default function RaceStrategy({ race, onBack }: { race: Race; onBack: () => void }) {
  const [st, setSt] = useState<Strategy | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [custom, setCustom] = useState('')
  const [start, setStart] = useState('')
  const [hover, setHover] = useState<number | null>(null)
  const [push, setPush] = useState<{ tone: 'ok' | 'bad' | 'info'; text: string } | null>(null)
  const c = useTokens()
  useEffect(() => {
    api.get<Strategy>(`/api/races/${race.id}/strategy`).then((s) => { setSt(s); setStart(s.start_time) }).catch((e) => setErr((e as Error).message))
  }, [race.id])
  const save = async (body: Record<string, unknown>) => {
    try { setSt(await api.put<Strategy>(`/api/races/${race.id}/strategy`, body)); setErr(null) } catch (e) { setErr((e as Error).message) }
  }
  const coords = st?.course.coords ?? null
  // km markers along the route: coords are evenly sampled along distance
  const marks = useMemo<Mark[]>(() => {
    if (!coords || !st) return []
    const n = coords.length - 1
    const total = st.course.distance_m
    const ms: Mark[] = [{ at: coords[0], label: 'Salida', kind: 'start' }, { at: coords[n], label: 'Meta', kind: 'finish' }]
    for (let k = 5000; k < total; k += 5000) ms.push({ at: coords[Math.round((k / total) * n)], label: `${k / 1000}`, kind: 'km' })
    return ms
  }, [coords, st])

  if (err && !st) return <div className="stack"><button className="btn btn-ghost btn-sm" onClick={onBack}>← {t('Races')}</button><Banner tone="bad">{err}</Banner></div>
  if (!st) return <div className="stack"><Skeleton h={120} /><Skeleton h={220} /><Skeleton h={300} /></div>

  const profile = st.course.profile.map(([d, e]) => ({ km: +(d / 1000).toFixed(2), ele: e }))
  const paceData = st.kms.map((k) => ({ ...k, label: `${k.km}`, fast: Math.max(...st.kms.map((x) => x.pace_s)) + 12 - k.pace_s }))
  const paces = st.kms.map((k) => k.pace_s)
  const lo = Math.min(...paces), hi = Math.max(...paces)
  const modes = Object.entries(st.prediction.modes)
  const w = st.weather

  return (
    <div className="stack">
      <div><button className="btn btn-ghost btn-sm" onClick={onBack}>← {t('Races')}</button></div>
      <div className="card hero" style={{ ['--hero-zone' as string]: 'var(--accent)' }}>
        <div className="micro">{t('Race strategy')} · {fmtDate(st.race.date, { weekday: 'long', day: 'numeric', month: 'long' })} · {st.start_time}</div>
        <h2 style={{ marginTop: 6 }}>{st.race.name}</h2>
        <div className="row" style={{ marginTop: 12, gap: 24, alignItems: 'flex-end' }}>
          <div><div className="micro">{t('Goal')}</div><div className="big-time">{fmtTime(st.target_s)}</div></div>
          <div><div className="micro">{t('Average')}</div><div className="num" style={{ fontSize: 22, fontWeight: 700 }}>{fmtPace(st.avg_pace_s)}/km</div></div>
          <div><div className="micro">{t('Halfway')}</div><div className="num" style={{ fontSize: 22, fontWeight: 700 }}>{fmtTime(st.half_s)}</div></div>
          <div><div className="micro">{t('Elevation gain')}</div><div className="num" style={{ fontSize: 22, fontWeight: 700 }}>+{st.course.gain_m} m</div></div>
        </div>
        <div className="row small" style={{ marginTop: 12 }}>
          {st.prediction.flat_s && <span className="chip">{t('On the flat you would run {time}', { time: fmtTime(st.prediction.flat_s) })} (VDOT {st.prediction.vdot})</span>}
          {st.course.factor > 1.005 && <span className="chip">{t('Course +{pct}% vs flat', { pct: ((st.course.factor - 1) * 100).toFixed(1) })}</span>}
          {w ? <span className={`chip chip-wrap ${st.heat_pct > 0 ? 'chip-warn' : ''}`}>{Math.round(w.temp)} °C · {t('dew point')} {Math.round(w.dew)} °C{w.rain_pct != null ? ` · ${t('rain')} ${w.rain_pct} %` : ''}{w.wind_kmh != null ? ` · ${t('wind')} ${Math.round(w.wind_kmh)} km/h` : ''}{st.heat_pct > 0 ? ` · ${t('+{pct}% for heat', { pct: st.heat_pct })}` : ''}</span>
            : <span className="chip">{t('Weather forecast available 16 days before')}</span>}
        </div>
      </div>

      <div className="card stack">
        <div className="card-head"><span className="micro">{t('Goal time')}</span></div>
        {modes.length > 0 && (
          <Segmented label={t('Goal')} value={st.mode === 'custom' || st.mode === 'goal' ? ('custom' as string) : st.mode} onChange={(m) => m !== 'custom' && save({ mode: m })}
            options={[...modes.map(([k, v]) => [k, `${MODE_LABEL[k]} ${fmtTime(v)}`] as [string, string]), ['custom', MODE_LABEL.custom]]} />
        )}
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <label className="field" style={{ maxWidth: 160 }}>{t('My time')}<input placeholder="h:mm:ss" value={custom} onChange={(e) => setCustom(e.target.value)} /></label>
          <button className="btn btn-sm" disabled={!custom} onClick={() => save({ target: custom })}>{t('Use')}</button>
          <label className="field" style={{ maxWidth: 120 }}>{t('Start time')}<input type="time" value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <button className="btn btn-sm" disabled={!start || start === st.start_time} onClick={() => save({ start_time: start })}>{t('Save')}</button>
        </div>
        <p className="small muted" style={{ margin: 0 }}>{t('Safe/Realistic/Ambitious come from your current VDOT, corrected for the course elevation')}{st.heat_pct > 0 ? ` ${t('and the forecast heat')}` : ''}. {t('My time: the goal you set.')}</p>
        {err && <Banner tone="bad">{err}</Banner>}
      </div>

      <div className="card">
        <div className="card-head"><span className="micro">{t('Profile and pace per km')}</span></div>
        <ResponsiveContainer width="100%" height={150}>
          <AreaChart data={profile} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
            onMouseMove={(e) => { const i = (e as { activeTooltipIndex?: number }).activeTooltipIndex; setHover(i != null && coords ? Math.round((i / Math.max(1, profile.length - 1)) * (coords.length - 1)) : null) }}
            onMouseLeave={() => setHover(null)}>
            <defs><linearGradient id="eleFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={c.accent} stopOpacity={0.35} /><stop offset="100%" stopColor={c.accent} stopOpacity={0.04} /></linearGradient></defs>
            <XAxis dataKey="km" type="number" domain={[0, 'dataMax']} stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} unit=" km" tickCount={6} />
            <YAxis stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} width={48} tickFormatter={(v) => `${Math.round(v)} m`}
              domain={[(min: number) => Math.max(0, Math.floor((min - 15) / 10) * 10), (max: number) => Math.ceil((max + 10) / 10) * 10]} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v} m`, 'Altitud']} labelFormatter={(l) => `km ${l}`} />
            <Area dataKey="ele" stroke={c.accent} strokeWidth={2} fill="url(#eleFill)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
        <ResponsiveContainer width="100%" height={150}>
          <BarChart data={paceData} margin={{ top: 12, right: 8, left: 48, bottom: 0 }} barCategoryGap={2}>
            <XAxis dataKey="label" stroke={c.muted} fontSize={11} tickLine={false} axisLine={false} interval={0} />
            <YAxis hide domain={[0, Math.ceil(hi - lo + 14)]} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: c.border, opacity: 0.4 }}
              formatter={(_v, _n, p) => [`${fmtPace((p?.payload as Km).pace_s)}/km`, t('Pace')]} labelFormatter={(l, p) => {
                const k = p?.[0]?.payload as Km | undefined
                return k ? `Km ${l} · ${TERRAIN_LABEL[k.terrain] ?? k.terrain}${k.grade_pct ? ` ${k.grade_pct > 0 ? '+' : ''}${k.grade_pct} %` : ''} · ${t('split')} ${fmtTime(k.cum_s)}` : `Km ${l}`
              }} />
            <Bar dataKey="fast" radius={[4, 4, 0, 0]} isAnimationActive={false}>
              {paceData.map((k) => <Cell key={k.km} fill={k.terrain === 'subida' ? c.up : k.terrain === 'bajada' ? c.down : c.flat} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="row small muted" style={{ justifyContent: 'center', gap: 14 }}>
          <span className="row" style={{ gap: 6 }}><span className="dot" style={{ background: 'var(--z4)' }} />{t('uphill')}</span>
          <span className="row" style={{ gap: 6 }}><span className="dot" style={{ background: 'var(--z2)' }} />{t('flat')}</span>
          <span className="row" style={{ gap: 6 }}><span className="dot" style={{ background: 'var(--z1)' }} />{t('downhill')}</span>
          <span>· {t('taller bar = faster')}</span>
        </div>
      </div>

      <CourseCard st={st} onCourse={(s) => { setSt(s); setErr(null) }} />

      {coords && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <Suspense fallback={<Skeleton h={280} />}><RouteMap coords={coords} marks={marks} highlight={hover} /></Suspense>
        </div>
      )}

      <div className="card">
        <div className="card-head row spread">
          <span className="micro">{t('Km-by-km plan')}</span>
          <button className="btn btn-primary btn-sm" onClick={async () => {
            setPush({ tone: 'info', text: t('Saving…') })
            try {
              const r = await api.post<{ garmin: { ok: boolean; error?: string } | null }>(`/api/races/${race.id}/strategy/push`)
              setPush(r.garmin ? (r.garmin.ok ? { tone: 'ok', text: t('On your watch: one step per km with its pace (±6 s). Sync Garmin Connect.') } : { tone: 'bad', text: t('Saved in the plan, but Garmin failed: {err}', { err: r.garmin.error ?? '' }) })
                : { tone: 'ok', text: t('Saved as the race-day workout. Connect Garmin to send it to the watch.') })
            } catch (e) { setPush({ tone: 'bad', text: (e as Error).message }) }
          }}><Icon name="watch" size={16} />{t('Send to watch')}</button>
        </div>
        {push && <div style={{ marginBottom: 10 }}><Banner tone={push.tone}>{push.text}</Banner></div>}
        <div className="splits">
          {st.kms.map((k) => (
            <div key={k.km} className="split" style={{ ['--tc' as string]: TERRAIN_COLOR[k.terrain] }}>
              <div className="split-km num">{k.km}</div>
              <div className="split-main">
                <div className="row" style={{ gap: 8 }}>
                  <b className="num">{fmtPace(k.pace_s)}/km</b>
                  <span className="small muted">{TERRAIN_LABEL[k.terrain] ?? k.terrain}{k.gain_m || k.loss_m ? ` · +${k.gain_m}/−${k.loss_m} m` : ''}</span>
                </div>
                {k.note && <div className="small text-2">{k.note}</div>}
              </div>
              <div className="split-cum num small muted">{fmtTime(k.cum_s)}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
        <div className="card">
          <div className="card-head"><span className="micro">{t('How to run it')}</span></div>
          <ul className="tips">{st.tips.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
        <div className="card">
          <div className="card-head"><span className="micro">{t('Food and drink')}</span></div>
          <ul className="tips">{st.fuel.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      </div>
      <p className="small muted">{t('Even-effort pacing over the profile (energy cost by gradient, Minetti 2002), a cautious start and heat adjustment (Hadley\'s rule). GPS km markers can differ slightly from the official ones.')}</p>
    </div>
  )
}
