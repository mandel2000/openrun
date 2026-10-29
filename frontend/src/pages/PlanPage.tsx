import { useCallback, useEffect, useState } from 'react'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { addDays, api, DAY_NAMES, daysBetween, DIST_LABEL, fmtDate, iso, PHASE_LABEL, useApi, workoutLevel, ZONE_LABEL, zoneLevel, zoneVar, type PaceRange, type Plan, type PlanWeek, type Race, type Workout } from '../api'
import WorkoutDetail from '../components/WorkoutDetail'
import { DragGhost, useWorkoutDrag } from '../components/dnd'
import { Banner, Icon, Sheet, Skeleton } from '../ui'
import { t } from '../i18n'


const GOALS = [['5k', '5K'], ['10k', '10K'], ['half', t('Half marathon')], ['marathon', t('Marathon')], ['base', t('Base / general fitness')]]
const DIST = [['5k', '5K'], ['10k', '10K'], ['half', t('Half')], ['marathon', t('Marathon')], ['mile', t('Mile')], ['3k', '3K']]

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
      <div className="card-head"><h2>{t('New plan')}</h2>{onCancel && <button type="button" className="btn btn-ghost" onClick={onCancel}>{t('Cancel')}</button>}</div>
      <p className="muted small">{t('Periodisation base → build → peak → taper, ~80/20 intensity, VDOT paces (Daniels) and ≤10%/week progression with recovery weeks.')}</p>
      <div className="form-grid">
        <label className="field">{t('Goal')}
          <select value={f.goal} onChange={(e) => set('goal', e.target.value)}>{GOALS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        <label className="field">{t('Race date')}
          <input type="date" value={f.race_date} onChange={(e) => set('race_date', e.target.value)} />
        </label>
        <label className="field">{t('…or number of weeks')}
          <input type="number" min={4} max={24} value={f.weeks} placeholder="auto" onChange={(e) => set('weeks', e.target.value)} />
        </label>
        <label className="field">{t('Goal time (optional)')}
          <input placeholder="1:45:00" value={f.goal_time} onChange={(e) => set('goal_time', e.target.value)} />
        </label>
        <label className="field">{t('Days per week')}
          <select value={f.days_per_week} onChange={(e) => set('days_per_week', +e.target.value)}>{[3, 4, 5, 6, 7].map((d) => <option key={d}>{d}</option>)}</select>
        </label>
        <label className="field">{t('Long run day')}
          <select value={f.long_run_day} onChange={(e) => set('long_run_day', +e.target.value)}>{DAY_NAMES.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>
        </label>
        <label className="field">{t('Current km/week')}
          <input type="number" value={f.current_weekly_km} onChange={(e) => set('current_weekly_km', +e.target.value)} />
        </label>
        <label className="field">{t('Longest recent run (km)')}
          <input type="number" value={f.longest_recent_run_km} onChange={(e) => set('longest_recent_run_km', +e.target.value)} />
        </label>
        <label className="field">{t('Level')}
          <select value={f.level} onChange={(e) => set('level', e.target.value)}>
            <option value="beginner">{t('Beginner')}</option><option value="intermediate">{t('Intermediate')}</option><option value="advanced">{t('Advanced')}</option>
          </select>
        </label>
        <label className="field">{t('Recent race: distance')}
          <select value={f.recent_race_distance} onChange={(e) => set('recent_race_distance', e.target.value)}>{DIST.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        <label className="field">{t('Recent race: time')}
          <input placeholder="45:30" value={f.recent_race_time} onChange={(e) => set('recent_race_time', e.target.value)} />
        </label>
        <label className="field">{t('Strength 2×/week')}
          <select value={f.include_strength ? '1' : '0'} onChange={(e) => set('include_strength', e.target.value === '1')}><option value="1">{t('Yes')}</option><option value="0">No</option></select>
        </label>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn btn-primary" disabled={busy}>{busy ? t('Generating…') : t('Generate plan')}</button>
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
      <div className="phasebar" role="img" aria-label={segs.map((s) => `${PHASE_LABEL[s.phase] ?? s.phase} ${t('{n} weeks', { n: s.count })}`).join(', ')}>
        {segs.map((s, i) => (
          <div key={i} style={{ flex: s.count, background: `color-mix(in srgb, ${PHASE_COLOR[s.phase] ?? 'var(--z0)'} 30%, var(--surface))` }}>
            {PHASE_LABEL[s.phase] ?? s.phase}
          </div>
        ))}
        {inRange(today) && <div className="phase-marker" style={{ left: `${pct(today)}%` }} title={t('Today')} />}
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
  const data = plan.weeks.map((w) => ({ name: `${t('W')}${w.index}`, index: w.index, plan: w.planned_km, done: w.done_km, low: w.low_intensity_pct }))
  return (
    <ResponsiveContainer width="100%" height={150}>
      <BarChart data={data} margin={{ top: 8, right: 4, left: -12, bottom: 0 }} barGap={-14}
        onClick={(e) => { const p = (e as { activePayload?: { payload: { index: number } }[] })?.activePayload?.[0]?.payload; if (p) onPick(p.index) }}>
        <XAxis dataKey="name" stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} />
        <YAxis stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} width={40} unit=" km" />
        <Tooltip cursor={{ fill: c.border, opacity: 0.4 }} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text)' }}
          formatter={(v, n) => [`${v} km`, n === 'plan' ? t('Planned') : t('Done')]}
          labelFormatter={(l, p) => `${l} · ${t('{pct}% low intensity', { pct: p?.[0]?.payload?.low ?? '' })}`} />
        <Bar dataKey="plan" fill={c.track} radius={[4, 4, 0, 0]} barSize={14} />
        <Bar dataKey="done" fill={c.accent} radius={[4, 4, 0, 0]} barSize={14} />
      </BarChart>
    </ResponsiveContainer>
  )
}

type DnD = ReturnType<typeof useWorkoutDrag>

function WChip({ w, onPick, dnd }: { w: Workout; onPick: (w: Workout) => void; dnd: DnD }) {
  const today = iso(new Date())
  const movable = w.status !== 'done' && w.date >= today
  const dragging = dnd.drag?.w.id === w.id
  return (
    <button className={`wchip ${w.status} ${w.date === today ? 'today' : ''} ${movable ? 'movable' : ''} ${dragging ? 'is-dragging' : ''}`}
      style={{ ['--zc' as string]: zoneVar(workoutLevel(w)) }}
      title={movable ? t('Drag to another day') : undefined}
      onPointerDown={movable ? (e) => dnd.start(w, e) : undefined}
      onContextMenu={movable ? (e) => e.preventDefault() : undefined}
      onClick={() => { if (!dnd.suppressClick.current) onPick(w) }}>
      <span className="t">{w.race_id ? '🏁 ' : ''}{w.title.replace(/^🏁\s*/, '')}</span>
      <span className="m row" style={{ gap: 6 }}>
        {w.sport === 'running' ? `${w.distance_km} km` : t('Strength')}
        {w.garmin_workout_id && <Icon name="watch" size={13} label={t('On Garmin')} />}
        {w.extra && <span>· {t('optional')}</span>}
        {w.status === 'modified' && <span>· {t('adjusted')}</span>}
      </span>
    </button>
  )
}

function WeekRow({ w, open, current, toggle, onPick, onAdd, dnd }: {
  w: PlanWeek; open: boolean; current: boolean; toggle: () => void; onPick: (w: Workout) => void; onAdd: (week: PlanWeek, date?: string) => void; dnd: DnD
}) {
  const today = iso(new Date())
  const days = Array.from({ length: 7 }, (_, i) => addDays(w.start, i))
  const byDay = days.map((d) => w.workouts.filter((x) => x.date === d))
  const pct = w.planned_km ? Math.min(100, (w.done_km / w.planned_km) * 100) : 0
  const id = `week-${w.index}`
  const dropCls = (d: string) => (dnd.drag ? (dnd.drag.over === d ? 'drop-over' : d >= today ? 'drop-ok' : '') : '')
  return (
    <section className="weekrow" id={id}>
      <button className={`weekhead ${current ? 'current' : ''}`} aria-expanded={open} aria-controls={`${id}-body`} onClick={toggle}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700 }}>
            {t('W')}{w.index} · {PHASE_LABEL[w.phase] ?? w.phase}{w.is_recovery ? ` · ${t('recovery week')}` : ''}
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
              <div className={`daycol ${dropCls(d)}`} key={d} data-drop-date={d >= today ? d : undefined}>
                <div className="dayhead" style={d === today ? { color: 'var(--accent-text)' } : undefined}>{DAY_NAMES[i]} {+d.slice(8)}</div>
                {byDay[i].map((x) => <WChip key={x.id} w={x} onPick={onPick} dnd={dnd} />)}
                {byDay[i].length === 0 && d >= today && <button className="addrun" onClick={() => onAdd(w, d)} aria-label={t('Add a run on {date}', { date: fmtDate(d) })}>+ {t('run')}</button>}
              </div>
            ))}
          </div>
          <div className="weeklist">
            {days.map((d, i) => (byDay[i].length > 0 || (dnd.drag && d >= today)) ? (
              <div key={d} className={`dayslot ${dropCls(d)}`} data-drop-date={d >= today ? d : undefined}>
                <div className="small muted" style={{ fontWeight: 600, marginBottom: 6 }}>{fmtDate(d, { weekday: 'long', day: 'numeric' })}</div>
                <div className="stack" style={{ gap: 6 }}>
                  {byDay[i].map((x) => <WChip key={x.id} w={x} onPick={onPick} dnd={dnd} />)}
                  {byDay[i].length === 0 && <div className="dropzone">{t('Rest · drop here')}</div>}
                </div>
              </div>
            ) : null)}
            {w.end >= today && <button className="btn btn-block" onClick={() => onAdd(w)}><Icon name="plus" />{t('Add run')}</button>}
          </div>
        </div>
      )}
    </section>
  )
}

function AddRunSheet({ week, date, onClose, onDone }: { week: PlanWeek; date?: string; onClose: () => void; onDone: (msg: string, warn: boolean) => void }) {
  const today = iso(new Date())
  const free = Array.from({ length: 7 }, (_, i) => addDays(week.start, i)).filter((d) => d >= today && !week.workouts.some((w) => w.date === d && w.sport === 'running' && w.status !== 'skipped'))
  const [d, setD] = useState(date ?? free[0] ?? '')
  const [km, setKm] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  return (
    <Sheet title={t('Add an easy run')} onClose={onClose} labelledBy="addrun-title">
      <p className="small text-2">{t('Optional run at easy pace (Z2): adds aerobic volume without breaking 80/20. You\'ll be warned if the week grows more than 10% or tomorrow is a key session.')}</p>
      {free.length === 0 ? <Banner tone="info">{t('No free days left this week.')}</Banner> : (
        <div className="form-grid">
          <label className="field">{t('Day')}
            <select value={d} onChange={(e) => setD(e.target.value)}>
              {free.map((x) => <option key={x} value={x}>{fmtDate(x, { weekday: 'long', day: 'numeric', month: 'short' })}</option>)}
            </select>
          </label>
          <label className="field">{t('Km (empty = automatic)')}
            <input type="number" min={2} max={25} step={0.5} inputMode="decimal" value={km} onChange={(e) => setKm(e.target.value)} placeholder="auto" />
          </label>
        </div>
      )}
      {err && <div style={{ marginTop: 12 }}><Banner tone="bad">{err}</Banner></div>}
      <div className="row" style={{ marginTop: 16, justifyContent: 'flex-end' }}>
        <button className="btn btn-ghost" onClick={onClose}>{t('Cancel')}</button>
        <button className="btn btn-primary" disabled={busy || !d} onClick={async () => {
          setBusy(true)
          try {
            const r = await api.post<{ title: string; week_km: number; warnings: string[] }>('/api/workouts/extra', { date: d, km: km ? +km : undefined })
            onDone([t('{title} added · week {km} km', { title: r.title, km: r.week_km }), ...r.warnings].join(' · '), r.warnings.length > 0)
          } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
        }}><Icon name="plus" />{t('Add')}</button>
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
  const [toast, setToast] = useState<{ tone: 'ok' | 'bad' | 'info'; text: string } | null>(null)
  const onDrop = useCallback(async (w: Workout, date: string) => {
    setToast({ tone: 'info', text: t('Moving “{title}”…', { title: w.title }) })
    try {
      const r = await api.post<{ moved: { id: number; title: string; date: string }[]; warnings: string[]; watch: { ok: number; failed: number } }>(`/api/workouts/${w.id}/move`, { date, swap: true })
      const swapped = r.moved.filter((x) => x.id !== w.id)
      const text = [`“${w.title}” → ${fmtDate(date, { weekday: 'long', day: 'numeric' })}`,
        ...swapped.map((x) => t('“{title}” moves to {date}', { title: x.title, date: fmtDate(x.date, { weekday: 'long', day: 'numeric' }) })),
        r.watch.failed ? t('Could not update the watch (reconnect Garmin in Settings)') : r.watch.ok ? t('Watch updated') : '', ...r.warnings].filter(Boolean).join(' · ')
      setToast({ tone: r.watch.failed ? 'bad' : r.warnings.length ? 'info' : 'ok', text })
      reload()
    } catch (e) { setToast({ tone: 'bad', text: (e as Error).message }) }
  }, [reload])
  const canDrop = useCallback((d: string) => d >= today, [today])
  const dnd = useWorkoutDrag(onDrop, canDrop)
  useEffect(() => {
    if (!toast || toast.text.endsWith('…')) return
    const id = window.setTimeout(() => setToast(null), toast.tone === 'ok' ? 4000 : 9000)
    return () => window.clearTimeout(id)
  }, [toast])

  if (plan === undefined) return <div className="stack"><Skeleton h={120} /><Skeleton h={160} /><Skeleton h={64} /><Skeleton h={64} /></div>
  if (!plan || creating) return <PlanForm onCreated={() => { setCreating(false); reload() }} onCancel={plan ? () => setCreating(false) : undefined} />

  const firstUpcoming = plan.weeks.find((w) => w.end >= today)
  const pushWeek = async (week: PlanWeek) => {
    setBusy(true)
    setMsg({ tone: 'info', text: t('Sending…') })
    try {
      const ids = week.workouts.filter((w) => w.sport === 'running' && w.status !== 'skipped' && w.status !== 'done' && w.date >= today).map((w) => w.id)
      const r = await api.post<{ ok: boolean; error?: string }[]>('/api/garmin/push', { ids })
      const ok = r.filter((x) => x.ok).length
      setMsg({ tone: ok === r.length ? 'ok' : 'bad', text: `${t('W')}${week.index}: ${t('{ok}/{n} workouts in Garmin Connect', { ok, n: r.length })}${r.some((x) => !x.ok) ? ` · ${r.find((x) => !x.ok)?.error}` : `. ${t('Sync your watch.')}`}` })
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
              <span className="num">{t('Starting VDOT')} {plan.vdot_start}{plan.vdot_goal ? ` → ${plan.vdot_goal}` : ''}</span>
            </div>
          </div>
          <div className="row">
            {firstUpcoming && <button className="btn btn-primary" disabled={busy} onClick={() => pushWeek(firstUpcoming)}><Icon name="watch" />{t('Send week {n} to watch', { n: firstUpcoming.index })}</button>}
            <button className="btn" onClick={() => setCreating(true)}>{t('New plan')}</button>
          </div>
        </div>
        {msg && <div style={{ marginTop: 12 }}><Banner tone={msg.tone}>{msg.text}</Banner></div>}
        {plan.warnings.map((w) => <div key={w} style={{ marginTop: 10 }}><Banner>{w}</Banner></div>)}
        <div style={{ marginTop: 18 }}><PhaseTimeline plan={plan} races={races.data ?? []} /></div>
        <div style={{ marginTop: 14 }}><VolumeChart plan={plan} onPick={scrollTo} /></div>
        <details style={{ marginTop: 8 }}>
          <summary className="small">{t('Training paces and predictions')}</summary>
          <div className="table-wrap"><table style={{ marginTop: 8 }}>
            <tbody>
              {paces.map(([k, p]) => (
                <tr key={k}><td><span className="row"><span className="zbar" style={{ ['--zc' as string]: zoneVar(zoneLevel(k)) }} />{ZONE_LABEL[k] ?? k}</span></td><td className="n">{p.slow_fmt}–{p.fast_fmt} /km</td></tr>
              ))}
              {Object.entries(plan.predictions_start).map(([k, p]) => (
                <tr key={k}><td>{t('Prediction')} {DIST_LABEL[k] ?? k}</td><td className="n">{p.time} → {plan.predictions_end[k]?.time}</td></tr>
              ))}
            </tbody>
          </table></div>
        </details>
      </div>
      <div>
        {plan.weeks.map((w) => (
          <WeekRow key={w.index} w={w} current={w.index === current} open={openW.has(w.index)} onPick={setPick} onAdd={(week, date) => setAdd({ week, date })} dnd={dnd}
            toggle={() => setOpenW((s) => { const n = new Set(s); if (n.has(w.index)) n.delete(w.index); else n.add(w.index); return n })} />
        ))}
      </div>
      <DragGhost drag={dnd.drag} />
      {toast && <div className="toast" role="status"><Banner tone={toast.tone}>{toast.text}</Banner></div>}
      {pick && <WorkoutDetail w={pick} onClose={() => setPick(null)} onChange={reload} />}
      {add && <AddRunSheet week={add.week} date={add.date} onClose={() => setAdd(null)}
        onDone={(text, warn) => { setAdd(null); setMsg({ tone: warn ? 'info' : 'ok', text }); reload() }} />}
    </div>
  )
}
