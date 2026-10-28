import { useEffect, useState } from 'react'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { addDays, api, DAY_NAMES, daysBetween, DIST_LABEL, fmtDate, iso, PHASE_LABEL, useApi, workoutLevel, ZONE_LABEL, zoneLevel, zoneVar, type PaceRange, type Plan, type PlanWeek, type Race, type Workout } from '../api'
import WorkoutDetail from '../components/WorkoutDetail'
import { Banner, Icon, Sheet, Skeleton } from '../ui'


const GOALS = [['5k', '5K'], ['10k', '10K'], ['half', 'Medio maratón'], ['marathon', 'Maratón'], ['base', 'Base / forma general']]
const DIST = [['5k', '5K'], ['10k', '10K'], ['half', 'Medio'], ['marathon', 'Maratón'], ['mile', 'Milla'], ['3k', '3K']]

export function PlanForm({ onCreated, onCancel, initial }: { onCreated: () => void; onCancel?: () => void; initial?: Record<string, unknown> }) {
  const [f, setF] = useState(() => ({
    goal: 'half', race_date: '', weeks: '', days_per_week: 4, long_run_day: 6, current_weekly_km: 25,
    longest_recent_run_km: 12, level: 'intermediate', recent_race_distance: '10k', recent_race_time: '', goal_time: '',
    include_strength: true, ...initial,
  }))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    const body: Record<string, unknown> = { ...f, weeks: f.weeks ? +f.weeks : undefined }
    for (const k of ['race_date', 'recent_race_time', 'goal_time']) if (!body[k]) delete body[k]
    if (!f.recent_race_time) delete body.recent_race_distance
    if (f.goal === 'base') delete body.goal_time
    try {
      await api.post('/api/plan', body)
      onCreated()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-head"><h2>Nuevo plan</h2>{onCancel && <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancelar</button>}</div>
      <p className="muted small">Periodización base → desarrollo → específico → afinamiento, ~80/20 de intensidad, ritmos por VDOT (Daniels) y progresión ≤10%/semana con descargas.</p>
      <div className="form-grid">
        <label className="field">Objetivo
          <select value={f.goal} onChange={(e) => set('goal', e.target.value)}>{GOALS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        <label className="field">Fecha de carrera
          <input type="date" value={f.race_date} onChange={(e) => set('race_date', e.target.value)} />
        </label>
        <label className="field">…o nº semanas
          <input type="number" min={4} max={24} value={f.weeks} placeholder="auto" onChange={(e) => set('weeks', e.target.value)} />
        </label>
        <label className="field">Tiempo objetivo (opcional)
          <input placeholder="1:45:00" value={f.goal_time} onChange={(e) => set('goal_time', e.target.value)} />
        </label>
        <label className="field">Días por semana
          <select value={f.days_per_week} onChange={(e) => set('days_per_week', +e.target.value)}>{[3, 4, 5, 6, 7].map((d) => <option key={d}>{d}</option>)}</select>
        </label>
        <label className="field">Día de tirada larga
          <select value={f.long_run_day} onChange={(e) => set('long_run_day', +e.target.value)}>{DAY_NAMES.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>
        </label>
        <label className="field">Km/semana actuales
          <input type="number" value={f.current_weekly_km} onChange={(e) => set('current_weekly_km', +e.target.value)} />
        </label>
        <label className="field">Tirada más larga reciente (km)
          <input type="number" value={f.longest_recent_run_km} onChange={(e) => set('longest_recent_run_km', +e.target.value)} />
        </label>
        <label className="field">Nivel
          <select value={f.level} onChange={(e) => set('level', e.target.value)}>
            <option value="beginner">Principiante</option><option value="intermediate">Intermedio</option><option value="advanced">Avanzado</option>
          </select>
        </label>
        <label className="field">Marca reciente: distancia
          <select value={f.recent_race_distance} onChange={(e) => set('recent_race_distance', e.target.value)}>{DIST.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        <label className="field">Marca reciente: tiempo
          <input placeholder="45:30" value={f.recent_race_time} onChange={(e) => set('recent_race_time', e.target.value)} />
        </label>
        <label className="field">Fuerza 2×/semana
          <select value={f.include_strength ? '1' : '0'} onChange={(e) => set('include_strength', e.target.value === '1')}><option value="1">Sí</option><option value="0">No</option></select>
        </label>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Generando…' : 'Generar plan'}</button>
        {err && <span className="err" role="alert">{err}</span>}
      </div>
    </form>
  )
}


const PHASE_COLOR: Record<string, string> = { base: 'var(--phase-base)', build: 'var(--phase-build)', peak: 'var(--phase-peak)', taper: 'var(--phase-taper)' }

function PhaseTimeline({ plan, races }: { plan: Plan; races: Race[] }) {
  const n = plan.weeks.length
  const segs: { phase: string; count: number }[] = []
  for (const w of plan.weeks) {
    const last = segs[segs.length - 1]
    if (last && last.phase === w.phase) last.count++
    else segs.push({ phase: w.phase, count: 1 })
  }
  const start = plan.weeks[0]?.start ?? plan.start_date
  const total = n * 7
  const pct = (d: string) => (daysBetween(start, d) / total) * 100
  const today = iso(new Date())
  const inRange = (d: string) => d >= start && daysBetween(start, d) < total
  return (
    <div style={{ paddingTop: races.some((r) => inRange(r.date)) ? 22 : 0 }}>
      <div className="phasebar" role="img" aria-label={segs.map((s) => `${PHASE_LABEL[s.phase] ?? s.phase} ${s.count} semanas`).join(', ')}>
        {segs.map((s, i) => (
          <div key={i} style={{ flex: s.count, background: `color-mix(in srgb, ${PHASE_COLOR[s.phase] ?? 'var(--z0)'} 30%, var(--surface))` }}>
            {PHASE_LABEL[s.phase] ?? s.phase}
          </div>
        ))}
        {inRange(today) && <div className="phase-marker" style={{ left: `${pct(today)}%` }} title="Hoy" />}
        {races.filter((r) => inRange(r.date)).map((r) => (
          <span key={r.id} className="phase-flag" style={{ left: `${pct(r.date)}%` }} title={`${r.name} (${r.priority})`}>
            <span className={`prio prio-${r.priority}`} style={{ width: 18, height: 18, fontSize: 10 }}>{r.priority}</span>
          </span>
        ))}
      </div>
      <div className="row spread small muted" style={{ marginTop: 6 }}>
        <span>{fmtDate(start, { day: 'numeric', month: 'short' })}</span>
        <span>{fmtDate(plan.weeks[n - 1]?.end ?? start, { day: 'numeric', month: 'short' })}</span>
      </div>
    </div>
  )
}

function useTokens() {
  const read = () => {
    const cs = getComputedStyle(document.documentElement)
    const g = (k: string) => cs.getPropertyValue(k).trim()
    return { accent: g('--accent'), track: g('--surface-3'), muted: g('--muted'), border: g('--border') }
  }
  const [t, setT] = useState(read)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = () => setT(read())
    mq.addEventListener('change', on)
    const mo = new MutationObserver(on)
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { mq.removeEventListener('change', on); mo.disconnect() }
  }, [])
  return t
}

function VolumeChart({ plan, onPick }: { plan: Plan; onPick: (i: number) => void }) {
  const c = useTokens()
  const data = plan.weeks.map((w) => ({ name: `S${w.index}`, index: w.index, plan: w.planned_km, done: w.done_km, low: w.low_intensity_pct }))
  return (
    <ResponsiveContainer width="100%" height={150}>
      <BarChart data={data} margin={{ top: 8, right: 4, left: -12, bottom: 0 }} barGap={-14}
        onClick={(e) => { const p = (e as { activePayload?: { payload: { index: number } }[] })?.activePayload?.[0]?.payload; if (p) onPick(p.index) }}>
        <XAxis dataKey="name" stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} />
        <YAxis stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} width={40} unit=" km" />
        <Tooltip cursor={{ fill: c.border, opacity: 0.4 }} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text)' }}
          formatter={(v, n) => [`${v} km`, n === 'plan' ? 'Planificado' : 'Hecho']}
          labelFormatter={(l, p) => `${l} · ${p?.[0]?.payload?.low ?? ''}% baja intensidad`} />
        <Bar dataKey="plan" fill={c.track} radius={[4, 4, 0, 0]} barSize={14} />
        <Bar dataKey="done" fill={c.accent} radius={[4, 4, 0, 0]} barSize={14} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function WChip({ w, onPick }: { w: Workout; onPick: (w: Workout) => void }) {
  const today = iso(new Date())
  return (
    <button className={`wchip ${w.status} ${w.date === today ? 'today' : ''}`} style={{ ['--zc' as string]: zoneVar(workoutLevel(w)) }} onClick={() => onPick(w)}>
      <span className="t">{w.race_id ? '🏁 ' : ''}{w.title.replace(/^🏁\s*/, '')}</span>
      <span className="m row" style={{ gap: 6 }}>
        {w.sport === 'running' ? `${w.distance_km} km` : 'Fuerza'}
        {w.garmin_workout_id && <Icon name="watch" size={13} label="En Garmin" />}
        {w.extra && <span>· opcional</span>}
        {w.status === 'modified' && <span>· ajustado</span>}
      </span>
    </button>
  )
}

function WeekRow({ w, open, current, toggle, onPick, onAdd }: {
  w: PlanWeek; open: boolean; current: boolean; toggle: () => void; onPick: (w: Workout) => void; onAdd: (week: PlanWeek, date?: string) => void
}) {
  const today = iso(new Date())
  const days = Array.from({ length: 7 }, (_, i) => addDays(w.start, i))
  const byDay = days.map((d) => w.workouts.filter((x) => x.date === d))
  const pct = w.planned_km ? Math.min(100, (w.done_km / w.planned_km) * 100) : 0
  const id = `week-${w.index}`
  return (
    <section className="weekrow" id={id}>
      <button className={`weekhead ${current ? 'current' : ''}`} aria-expanded={open} aria-controls={`${id}-body`} onClick={toggle}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700 }}>
            S{w.index} · {PHASE_LABEL[w.phase] ?? w.phase}{w.is_recovery ? ' · descarga' : ''}
            <span className="muted" style={{ fontWeight: 500 }}> · {fmtDate(w.start, { day: 'numeric', month: 'short' })}–{fmtDate(w.end, { day: 'numeric', month: 'short' })}</span>
          </div>
          <div className="row small muted" style={{ marginTop: 6, flexWrap: 'nowrap' }}>
            <div className="progress grow" style={{ maxWidth: 220 }}><span style={{ width: `${pct}%` }} /></div>
            <span className="num">{w.done_km}/{w.planned_km} km</span>
            <span className="num" style={{ whiteSpace: 'nowrap' }}>· {w.low_intensity_pct}% Z1–2</span>
          </div>
        </div>
        <Icon name="chevronDown" size={20} className="muted" />
      </button>
      {open && (
        <div id={`${id}-body`}>
          <div className="days7">
            {days.map((d, i) => (
              <div className="daycol" key={d}>
                <div className="dayhead" style={d === today ? { color: 'var(--accent-text)' } : undefined}>{DAY_NAMES[i]} {+d.slice(8)}</div>
                {byDay[i].map((x) => <WChip key={x.id} w={x} onPick={onPick} />)}
                {byDay[i].length === 0 && d >= today && <button className="addrun" onClick={() => onAdd(w, d)} aria-label={`Añadir rodaje el ${fmtDate(d)}`}>+ rodaje</button>}
              </div>
            ))}
          </div>
          <div className="weeklist">
            {days.map((d, i) => byDay[i].length > 0 && (
              <div key={d} style={{ marginBottom: 10 }}>
                <div className="small muted" style={{ fontWeight: 600, marginBottom: 6 }}>{fmtDate(d, { weekday: 'long', day: 'numeric' })}</div>
                <div className="stack" style={{ gap: 6 }}>{byDay[i].map((x) => <WChip key={x.id} w={x} onPick={onPick} />)}</div>
              </div>
            ))}
            {w.end >= today && <button className="btn btn-block" onClick={() => onAdd(w)}><Icon name="plus" />Añadir rodaje</button>}
          </div>
        </div>
      )}
    </section>
  )
}

function AddRunSheet({ week, date, onClose, onDone }: { week: PlanWeek; date?: string; onClose: () => void; onDone: (msg: string) => void }) {
  const today = iso(new Date())
  const free = Array.from({ length: 7 }, (_, i) => addDays(week.start, i)).filter((d) => d >= today && !week.workouts.some((w) => w.date === d && w.sport === 'running' && w.status !== 'skipped'))
  const [d, setD] = useState(date ?? free[0] ?? '')
  const [km, setKm] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  return (
    <Sheet title="Añadir rodaje suave" onClose={onClose} labelledBy="addrun-title">
      <p className="small text-2">Rodaje opcional a ritmo suave (Z2): suma volumen aeróbico sin romper el 80/20. Te avisaremos si la semana sube más de un 10 % o si mañana tienes sesión clave.</p>
      {free.length === 0 ? <Banner tone="info">No quedan días libres esta semana.</Banner> : (
        <div className="form-grid">
          <label className="field">Día
            <select value={d} onChange={(e) => setD(e.target.value)}>
              {free.map((x) => <option key={x} value={x}>{fmtDate(x, { weekday: 'long', day: 'numeric', month: 'short' })}</option>)}
            </select>
          </label>
          <label className="field">Km (vacío = automático)
            <input type="number" min={2} max={25} step={0.5} inputMode="decimal" value={km} onChange={(e) => setKm(e.target.value)} placeholder="auto" />
          </label>
        </div>
      )}
      {err && <div style={{ marginTop: 12 }}><Banner tone="bad">{err}</Banner></div>}
      <div className="row" style={{ marginTop: 16, justifyContent: 'flex-end' }}>
        <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
        <button className="btn btn-primary" disabled={busy || !d} onClick={async () => {
          setBusy(true)
          try {
            const r = await api.post<{ title: string; week_km: number; warnings: string[] }>('/api/workouts/extra', { date: d, km: km ? +km : undefined })
            onDone([`${r.title} añadido · semana ${r.week_km} km`, ...r.warnings].join(' · '))
          } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
        }}><Icon name="plus" />Añadir</button>
      </div>
    </Sheet>
  )
}

export default function PlanPage({ plan, reload }: { plan: Plan | null | undefined; reload: () => void }) {
  const [creating, setCreating] = useState(false)
  const [pick, setPick] = useState<Workout | null>(null)
  const [add, setAdd] = useState<{ week: PlanWeek; date?: string } | null>(null)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad' | 'info'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const races = useApi<Race[]>('/api/races')
  const today = iso(new Date())
  const current = plan?.weeks.find((w) => w.start <= today && today <= w.end)?.index ?? plan?.weeks.find((w) => w.start > today)?.index ?? 1
  const [openW, setOpenW] = useState<Set<number>>(() => new Set([current]))

  if (plan === undefined) return <div className="stack"><Skeleton h={120} /><Skeleton h={160} /><Skeleton h={64} /><Skeleton h={64} /></div>
  if (!plan || creating) return <PlanForm onCreated={() => { setCreating(false); reload() }} onCancel={plan ? () => setCreating(false) : undefined} />

  const firstUpcoming = plan.weeks.find((w) => w.end >= today)
  const pushWeek = async (week: PlanWeek) => {
    setBusy(true)
    setMsg({ tone: 'info', text: 'Enviando…' })
    try {
      const ids = week.workouts.filter((w) => w.sport === 'running' && w.status !== 'skipped' && w.status !== 'done' && w.date >= today).map((w) => w.id)
      const r = await api.post<{ ok: boolean; error?: string }[]>('/api/garmin/push', { ids })
      const ok = r.filter((x) => x.ok).length
      setMsg({ tone: ok === r.length ? 'ok' : 'bad', text: `S${week.index}: ${ok}/${r.length} entrenos en Garmin Connect${r.some((x) => !x.ok) ? ` · ${r.find((x) => !x.ok)?.error}` : '. Sincroniza el reloj.'}` })
      reload()
    } catch (e) {
      setMsg({ tone: 'bad', text: (e as Error).message })
    } finally { setBusy(false) }
  }
  const scrollTo = (i: number) => {
    setOpenW((s) => new Set(s).add(i))
    setTimeout(() => document.getElementById(`week-${i}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }
  const paces = Object.entries(plan.paces_start).filter(([k]) => k !== 'vdot') as [string, PaceRange][]

  return (
    <div className="stack">
      <div className="card">
        <div className="row spread">
          <div style={{ minWidth: 0 }}>
            <h2>{plan.name}</h2>
            <div className="row small muted" style={{ marginTop: 6 }}>
              <span className="chip">{plan.goal.toUpperCase()}</span>
              <span>{fmtDate(plan.start_date, { day: 'numeric', month: 'short' })} → {plan.race_date ? fmtDate(plan.race_date, { day: 'numeric', month: 'short' }) : fmtDate(plan.weeks[plan.weeks.length - 1].end, { day: 'numeric', month: 'short' })}</span>
              <span className="num">VDOT inicial {plan.vdot_start}{plan.vdot_goal ? ` → ${plan.vdot_goal}` : ''}</span>
            </div>
          </div>
          <div className="row">
            {firstUpcoming && <button className="btn btn-primary" disabled={busy} onClick={() => pushWeek(firstUpcoming)}><Icon name="watch" />Enviar S{firstUpcoming.index} al reloj</button>}
            <button className="btn" onClick={() => setCreating(true)}>Nuevo plan</button>
          </div>
        </div>
        {msg && <div style={{ marginTop: 12 }}><Banner tone={msg.tone}>{msg.text}</Banner></div>}
        {plan.warnings.map((w) => <div key={w} style={{ marginTop: 10 }}><Banner>{w}</Banner></div>)}
        <div style={{ marginTop: 18 }}><PhaseTimeline plan={plan} races={races.data ?? []} /></div>
        <div style={{ marginTop: 14 }}><VolumeChart plan={plan} onPick={scrollTo} /></div>
        <details style={{ marginTop: 8 }}>
          <summary className="small">Ritmos de entrenamiento y predicciones</summary>
          <div className="table-wrap"><table style={{ marginTop: 8 }}>
            <tbody>
              {paces.map(([k, p]) => (
                <tr key={k}><td><span className="row"><span className="zbar" style={{ ['--zc' as string]: zoneVar(zoneLevel(k)) }} />{ZONE_LABEL[k] ?? k}</span></td><td className="n">{p.slow_fmt}–{p.fast_fmt} /km</td></tr>
              ))}
              {Object.entries(plan.predictions_start).map(([k, p]) => (
                <tr key={k}><td>Predicción {DIST_LABEL[k] ?? k}</td><td className="n">{p.time} → {plan.predictions_end[k]?.time}</td></tr>
              ))}
            </tbody>
          </table></div>
        </details>
      </div>
      <div>
        {plan.weeks.map((w) => (
          <WeekRow key={w.index} w={w} current={w.index === current} open={openW.has(w.index)} onPick={setPick} onAdd={(week, date) => setAdd({ week, date })}
            toggle={() => setOpenW((s) => { const n = new Set(s); if (n.has(w.index)) n.delete(w.index); else n.add(w.index); return n })} />
        ))}
      </div>
      {pick && <WorkoutDetail w={pick} onClose={() => setPick(null)} onChange={reload} />}
      {add && <AddRunSheet week={add.week} date={add.date} onClose={() => setAdd(null)}
        onDone={(t) => { setAdd(null); setMsg({ tone: t.includes('%') || t.includes('Mañana') || t.includes('doble') ? 'info' : 'ok', text: t }); reload() }} />}
    </div>
  )
}
