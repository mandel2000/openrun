import { useState } from 'react'
import { addDays, api, DAY_NAMES, type Weather, daysBetween, fmtDate, fmtTime, iso, PHASE_LABEL, useApi, workoutLevel, zoneVar, type Plan, type Race, type Workout } from '../api'
import ActivityAnalysisSheet from '../components/ActivityAnalysis'
import StepProfile from '../components/StepProfile'
import WorkoutDetail, { Steps, WorkoutMeta } from '../components/WorkoutDetail'
import { Banner, Empty, Icon, Skeleton } from '../ui'
import ReadinessCard from '../components/ReadinessCard'
import { ReplanCard } from '../components/Replan'
import { t } from '../i18n'

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

function WeatherChip({ date, w, onAdjusted }: { date: string; w: Workout; onAdjusted: () => void }) {
  const { data } = useApi<Weather>(`/api/weather?date=${date}`)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  if (!data || data.available === false || w.sport !== 'running') return null
  const heated = !!(w as Workout & { _heat?: unknown })._heat
  return (
    <div style={{ marginTop: 12 }}>
      <div className="row">
        <span className={`chip ${data.pct >= 1 ? 'chip-warn' : ''}`} title={t('Temperature + dew point = {f} °F', { f: data.sum_f })}>
          <Icon name="sun" size={14} />{t('{temp} °C · dew point {dew} °C at {hour}h', { temp: Math.round(data.temp), dew: Math.round(data.dew), hour: data.hour })}
          {data.pct >= 1 ? ` · ${t('pace +{pct}%', { pct: data.pct })}` : ''}
        </span>
        {data.pct >= 1 && !heated && (
          <button className="btn btn-sm" disabled={busy} onClick={async () => {
            setBusy(true)
            try {
              const r = await api.post<{ changes: unknown[]; pushed: number }>('/api/heat/apply')
              setMsg(t('{n} workouts adjusted for heat', { n: r.changes.length }) + (r.pushed ? t(', {n} updated on the watch', { n: r.pushed }) : '') + '.')
              onAdjusted()
            } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
          }}>{t('Adjust for heat')}</button>
        )}
        {heated && <span className="chip chip-good"><Icon name="check" size={13} />{t('Adjusted for heat')}</span>}
      </div>
      {data.too_hot && <div style={{ marginTop: 8 }}><Banner>{t('Extreme heat: run first thing in the morning, on a treadmill, or swap it for an easy run. Drink before and during.')}</Banner></div>}
      {msg && <div className="small muted" style={{ marginTop: 6 }}>{msg}</div>}
    </div>
  )
}

function Hero({ w, date, onOpen, onPushed }: { w: Workout | null; date: string; onOpen: (w: Workout) => void; onPushed: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [an, setAn] = useState(false)
  const today = iso(new Date())
  const label = date === today ? t('Today') : fmtDate(date, { weekday: 'long', day: 'numeric', month: 'short' })
  if (!w)
    return (
      <div className="card hero" style={{ ['--hero-zone' as string]: 'var(--z0)' }}>
        <div className="micro">{label}</div>
        <h2 style={{ marginTop: 6 }}>{t('Rest')}</h2>
        <p className="text-2" style={{ marginTop: 6 }}>{t('Sleeping well and eating enough is training too. Adaptation happens during recovery.')}</p>
      </div>
    )
  const lvl = workoutLevel(w)
  return (
    <div className="card hero" style={{ ['--hero-zone' as string]: zoneVar(lvl) }}>
      <div className="row spread">
        <span className="micro">{label}</span>
        <div className="row">
          {w.status === 'done' && <span className="chip chip-good"><Icon name="check" size={14} />{t('Completed')}</span>}
          {w.status === 'modified' && <span className="chip chip-warn">{t('Adjusted')}</span>}
          {w.extra && <span className="chip chip-outline">{t('Optional')}</span>}
        </div>
      </div>
      <h2 style={{ marginTop: 6, fontSize: 28, lineHeight: '34px' }}>{w.title}</h2>
      <div className="text-2 num" style={{ marginTop: 4 }}><WorkoutMeta w={w} /> · Z{lvl}</div>
      {w.sport === 'running' && <div style={{ marginTop: 16 }}><StepProfile steps={w.steps} /></div>}
      {w.status !== 'done' && date >= iso(new Date()) && daysBetween(iso(new Date()), date) <= 2 && <WeatherChip date={date} w={w} onAdjusted={onPushed} />}
      {w.note && <div style={{ marginTop: 12 }}><Banner>{w.note}</Banner></div>}
      <details style={{ marginTop: 12 }}>
        <summary className="small">{t('Steps and rationale')}</summary>
        <p className="small text-2" style={{ marginTop: 8 }}>{w.description}</p>
        {w.sport === 'running' && <Steps steps={w.steps} />}
      </details>
      <div className="row" style={{ marginTop: 16 }}>
        {w.status === 'done' && w.activity_id
          ? <button className="btn btn-primary" onClick={() => setAn(true)}><Icon name="activity" />{t('Actual vs plan')}</button>
          : <button className="btn btn-primary" onClick={() => onOpen(w)}>{t('View details')}</button>}
        {w.status === 'done' && w.activity_id && <button className="btn" onClick={() => onOpen(w)}>{t('View workout')}</button>}
        {w.sport === 'running' && (
          <button className="btn" disabled={busy} onClick={async () => {
            setBusy(true)
            setErr(null)
            try {
              const r = await api.post<{ ok: boolean; error?: string }[]>('/api/garmin/push', { ids: [w.id] })
              if (!r[0]?.ok) throw new Error(r[0]?.error ?? 'error')
              onPushed()
            } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
          }}>
            <Icon name={w.garmin_workout_id ? 'check' : 'watch'} />{w.garmin_workout_id ? t('On the watch') : busy ? t('Sending…') : t('Send to watch')}
          </button>
        )}
      </div>
      {err && <div style={{ marginTop: 10 }}><Banner tone="bad">{err}</Banner></div>}
      {an && w.activity_id && <ActivityAnalysisSheet activityId={w.activity_id} title={w.title} initial="plan" onClose={() => setAn(false)} />}
    </div>
  )
}

function WeekStrip({ monday, byDate, sel, onSel }: { monday: string; byDate: Map<string, Workout[]>; sel: string; onSel: (d: string) => void }) {
  const today = iso(new Date())
  return (
    <div className="weekstrip" role="group" aria-label={t('Week')}>
      {DAY_NAMES.map((dn, i) => {
        const d = addDays(monday, i)
        const ws = (byDate.get(d) ?? []).filter((w) => w.status !== 'skipped')
        const runs = ws.filter((w) => w.sport === 'running')
        const done = runs.length > 0 && runs.every((w) => w.status === 'done')
        return (
          <button key={d} className={`daycell ${d === today ? 'today' : ''}`} aria-pressed={d === sel} onClick={() => onSel(d)}
            aria-label={`${fmtDate(d, { weekday: 'long', day: 'numeric' })}: ${ws.map((w) => w.title).join(', ') || t('rest')}`}>
            <span className="dname">{dn}</span>
            <span className="dnum">{+d.slice(8)}</span>
            <span className="bars">
              {ws.map((w) => <span key={w.id} className={w.extra ? 'extra' : ''} style={{ ['--zc' as string]: zoneVar(workoutLevel(w)) }} />)}
            </span>
            {done && <Icon name="check" size={14} className="done" />}
          </button>
        )
      })}
    </div>
  )
}

type Review = { week_start: string; comment: string; ai: boolean
  facts: { km: number; km_plan: number; carreras: number; sesiones_plan: number; hechas: number; cumplimiento_pct: number | null
    carga: { ctl: number | null; ctl_cambio: number | null; tsb: number | null; acwr: number | null } } }

function WeeklyReviewCard() {
  const { data, loading, setData } = useApi<Review>('/api/weekly-review')
  const [busy, setBusy] = useState(false)
  if (loading && !data) return <div className="card"><div className="micro">{t('Last week')}</div><Skeleton h={60} style={{ marginTop: 10 }} /></div>
  if (!data) return null
  const f = data.facts
  const end = addDays(data.week_start, 6)
  return (
    <div className="card">
      <div className="row spread">
        <div className="micro">{t('Last week')} · {fmtDate(data.week_start, { day: 'numeric', month: 'short' })}–{fmtDate(end, { day: 'numeric', month: 'short' })}</div>
        <button className="btn btn-ghost btn-icon btn-sm" aria-label={t('Regenerate summary')} disabled={busy} onClick={async () => {
          setBusy(true)
          try { setData(await api.post<Review>('/api/weekly-review')) } finally { setBusy(false) }
        }}><Icon name="refresh" size={16} className={busy ? 'spin' : ''} /></button>
      </div>
      <div className="mini-stats" style={{ marginTop: 10 }}>
        <div><span className="micro">Km</span><b>{f.km}{f.km_plan ? <small> / {f.km_plan}</small> : null}</b></div>
        <div><span className="micro">{t('Sessions')}</span><b>{f.sesiones_plan ? `${f.hechas}/${f.sesiones_plan}` : f.carreras}</b></div>
        <div><span className="micro">{t('Fitness (CTL)')}</span><b>{f.carga.ctl ?? '–'}{f.carga.ctl_cambio ? <small> {f.carga.ctl_cambio > 0 ? '+' : ''}{f.carga.ctl_cambio}</small> : null}</b></div>
        <div><span className="micro">ACWR</span><b>{f.carga.acwr ?? '–'}</b></div>
      </div>
      <p className="text-2" style={{ marginTop: 12, marginBottom: 0, whiteSpace: 'pre-wrap' }}>{data.comment}</p>
      {data.ai && <div className="small muted" style={{ marginTop: 6 }}><Icon name="sparkles" size={13} /> {t('AI coach comment')}</div>}
    </div>
  )
}

function RaceSoonCard({ r }: { r: Race }) {
  return (
    <a className="card race-soon" href={`#carreras/estrategia/${r.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
      <div className="row spread" style={{ flexWrap: 'nowrap' }}>
        <div style={{ minWidth: 0 }}>
          <div className="micro">{r.days_to_go === 0 ? t('Race day!') : r.days_to_go === 1 ? t('Tomorrow') : t('In {n} days', { n: r.days_to_go })}</div>
          <div style={{ fontWeight: 700, fontSize: 18, marginTop: 4 }}>🏁 {r.name}</div>
          <div className="small muted">{r.strategy_target_s ? `${t('Goal')} ${fmtTime(r.strategy_target_s)} · ` : ''}{t('Pace per km, elevation, weather and fuelling')}</div>
        </div>
        <span className="btn btn-primary btn-sm" style={{ flex: 'none' }}>{t('Strategy')}<Icon name="chevronRight" size={16} /></span>
      </div>
    </a>
  )
}

export default function TodayPage({ plan, reload, go }: { plan: Plan | null | undefined; reload: () => void; go: (t: string) => void }) {
  const today = iso(new Date())
  const races = useApi<Race[]>('/api/races')
  const [sel, setSel] = useState<string | null>(null)
  const [pick, setPick] = useState<Workout | null>(null)

  if (plan === undefined) return <div className="stack"><Skeleton h={28} w={240} /><Skeleton h={260} /><Skeleton h={90} /></div>

  const all = plan?.weeks.flatMap((w) => w.workouts) ?? []
  const byDate = new Map<string, Workout[]>()
  for (const w of all) byDate.set(w.date, [...(byDate.get(w.date) ?? []), w])
  const started = plan ? today >= plan.start_date : false
  const weekNow = plan?.weeks.find((w) => w.start <= today && today <= w.end)
  const focusWeek = weekNow ?? (plan && !started ? plan.weeks[0] : null)
  const monday = focusWeek?.start ?? addDays(today, -((new Date().getDay() + 6) % 7))
  const selDay = sel ?? (focusWeek && !weekNow ? (focusWeek.workouts.find((w) => w.sport === 'running')?.date ?? monday) : today)
  const dayWs = (byDate.get(selDay) ?? []).filter((w) => w.status !== 'skipped')
  const heroW = dayWs.find((w) => w.sport === 'running') ?? dayWs[0] ?? null
  const otherWs = dayWs.filter((w) => w !== heroW)
  const nextA = races.data?.find((r) => r.priority === 'A' && r.days_to_go >= 0)
  const nextRace = nextA ?? races.data?.find((r) => r.days_to_go >= 0)

  return (
    <div className="stack">
      <div className="row spread">
        <div>
          <div className="text-2" style={{ fontWeight: 600 }}>{cap(fmtDate(today, { weekday: 'long', day: 'numeric', month: 'long' }))}</div>
          {weekNow && plan && <div className="small muted">{t('Week {n}/{total}', { n: weekNow.index, total: plan.weeks.length })} · {PHASE_LABEL[weekNow.phase] ?? weekNow.phase}{weekNow.is_recovery ? ` · ${t('recovery week')}` : ''}</div>}
        </div>
        {nextRace && (
          <a href="#carreras" className="chip" style={{ textDecoration: 'none' }}>
            <span className={`prio prio-${nextRace.priority}`} style={{ width: 18, height: 18, fontSize: 10 }}>{nextRace.priority}</span>
            {nextRace.name.length > 28 ? nextRace.name.slice(0, 26) + '…' : nextRace.name} · {nextRace.days_to_go} d
          </a>
        )}
      </div>

      {nextRace && nextRace.days_to_go <= 21 && (nextRace.distance_m ?? 0) >= 3000 && <RaceSoonCard r={nextRace} />}

      {!plan ? (
        <div className="card">
          <Empty icon="calendar" title={t('No active plan')}>{t('Create a plan for your goal or ask the coach for one.')}</Empty>
          <div className="row" style={{ justifyContent: 'center' }}>
            <button className="btn btn-primary" onClick={() => go('plan')}>{t('Create plan')}</button>
            <button className="btn" onClick={() => go('coach')}>{t('Talk to the coach')}</button>
          </div>
        </div>
      ) : (
        <>
          {!started && (
            <div className="card">
              <div className="row spread">
                <div>
                  <div className="micro">{t('Before the plan')}</div>
                  <div style={{ fontWeight: 600, marginTop: 4 }}>{t('Your plan “{name}” starts on {date} (in {n} days).', { name: plan.name, date: fmtDate(plan.start_date, { weekday: 'long', day: 'numeric', month: 'long' }), n: daysBetween(today, plan.start_date) })}</div>
                  <div className="small muted">{t('Until then, keep following your current plan. Here is the first week.')}</div>
                </div>
                <button className="btn" onClick={() => go('plan')}>{t('View plan')}<Icon name="chevronRight" size={16} /></button>
              </div>
            </div>
          )}
          <div className="grid-2">
            <div className="stack">
              <Hero w={heroW} date={selDay} onOpen={setPick} onPushed={reload} />
              {otherWs.map((w) => (
                <button key={w.id} className="card list-row" style={{ padding: '12px 16px' }} onClick={() => setPick(w)}>
                  <Icon name={w.sport === 'strength' ? 'dumbbell' : 'activity'} />
                  <div className="grow"><div className="title">{w.title}</div><div className="meta"><WorkoutMeta w={w} /></div></div>
                  <Icon name="chevronRight" size={16} />
                </button>
              ))}
              <div className="card">
                <div className="card-head">
                  <span className="micro">{weekNow ? t('This week') : t('Week 1 of the plan')}</span>
                  {focusWeek && <span className="small muted num">{focusWeek.done_km} / {focusWeek.planned_km} km</span>}
                </div>
                <WeekStrip monday={monday} byDate={byDate} sel={selDay} onSel={setSel} />
              </div>
            </div>
            <div className="stack">
              <ReplanCard onChanged={reload} />
              <ReadinessCard onChanged={reload} />
            </div>
          </div>
        </>
      )}
      <WeeklyReviewCard />
      {pick && <WorkoutDetail w={pick} onClose={() => setPick(null)} onChange={reload} />}
    </div>
  )
}
