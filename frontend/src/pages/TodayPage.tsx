import { useState } from 'react'
import { addDays, api, DAY_NAMES, type Weather, daysBetween, fmtDate, fmtTime, iso, PHASE_LABEL, useApi, workoutLevel, zoneVar, type Plan, type Race, type Readiness, type Workout } from '../api'
import ActivityAnalysisSheet from '../components/ActivityAnalysis'
import StepProfile from '../components/StepProfile'
import WorkoutDetail, { Steps, WorkoutMeta } from '../components/WorkoutDetail'
import { Banner, Empty, Icon, Skeleton } from '../ui'

type WRow = { date: string; hrv_rmssd?: number; rest_hr?: number; sleep_score?: number; sleep_hours?: number; body_battery?: number; training_readiness?: number }
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const RLABEL = { green: 'Listo para entrenar', amber: 'Fatiga moderada', red: 'Recupera hoy', unknown: 'Sin datos suficientes' }
const RICON = { green: 'check', amber: 'alert', red: 'x', unknown: 'heart' } as const

function ReadinessCard({ onChanged }: { onChanged: () => void }) {
  const { data, loading, reload } = useApi<{ rows: WRow[]; readiness: Readiness }>('/api/wellness?days=70')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [more, setMore] = useState(false)
  const run = async (fn: () => Promise<string>) => {
    setBusy(true)
    try { setMsg(await fn()); onChanged(); reload() } catch (e) { setMsg(`Error: ${(e as Error).message}`) } finally { setBusy(false) }
  }
  if (loading && !data) return <div className="card"><Skeleton h={56} w={56} style={{ borderRadius: '50%' }} /><Skeleton h={14} style={{ marginTop: 12 }} /><Skeleton h={14} w="60%" style={{ marginTop: 8 }} /></div>
  const r = data?.readiness
  const st = r?.status ?? 'unknown'
  const last = [...(data?.rows ?? [])].reverse().find((x) => x.sleep_score || x.hrv_rmssd || x.body_battery)
  const lo = r?.swc_low, hi = r?.swc_high, v = r?.hrv_7d
  const min = lo && hi ? lo - (hi - lo) : 0, max = lo && hi ? hi + (hi - lo) : 1
  const pos = (x: number) => `${Math.min(100, Math.max(0, ((x - min) / (max - min)) * 100))}%`
  return (
    <div className="card">
      <div className="card-head"><span className="micro">Readiness</span><a className="small" href="#ajustes">Medir HRV</a></div>
      <div className="row" style={{ gap: 14, flexWrap: 'nowrap' }}>
        <div className={`ring ready-${st}`}><Icon name={RICON[st]} size={24} /></div>
        <div className="grow">
          <div style={{ fontWeight: 700, fontSize: 17 }} className={`ready-${st}`}>{RLABEL[st]}</div>
          {v && <div className="small muted num">HRV 7 d {v} ms · normal {lo}–{hi}</div>}
        </div>
      </div>
      {v && lo && hi && (
        <div className="bullet" aria-hidden>
          <div className="band" style={{ left: pos(lo), width: `calc(${pos(hi)} - ${pos(lo)})` }} />
          <div className="mark" style={{ left: pos(v) }} />
        </div>
      )}
      {!!r?.reasons.length && <ul className="small text-2" style={{ margin: '8px 0', paddingLeft: 18 }}>{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}
      {last && (
        <div className="mini-stats" style={{ marginTop: 12 }}>
          <div><span className="micro">Sueño</span><b>{last.sleep_score ?? '–'}</b></div>
          <div><span className="micro">FC reposo</span><b>{last.rest_hr ?? '–'}</b></div>
          <div><span className="micro">Readiness Garmin</span><b>{last.training_readiness ?? '–'}</b></div>
          <div><span className="micro">Body Battery</span><b>{last.body_battery ?? '–'}</b></div>
        </div>
      )}
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn btn-sm" disabled={busy} onClick={() => run(async () => {
          const x = await api.post<{ changes: { title: string; reason: string }[] }>('/api/adapt-today')
          return x.changes.length ? x.changes.map((c) => `${c.title}: ${c.reason}`).join('\n') : 'Sin cambios necesarios hoy.'
        })}><Icon name="zap" size={16} />Ajustar hoy</button>
        <button className="btn btn-sm btn-ghost" aria-expanded={more} onClick={() => setMore(!more)}>¿No estás al 100%?<Icon name="chevronDown" size={16} /></button>
      </div>
      {more && (
        <div style={{ marginTop: 10 }}>
          <p className="small muted">Calidad → suave y −30 % de volumen durante unos días, o descanso activo.</p>
          <div className="row">
            {[3, 5, 7].map((d) => (
              <button key={d} className="btn btn-sm" disabled={busy} onClick={() => run(async () => {
                const x = await api.post<unknown[]>('/api/not-feeling-100', { days: d, mode: 'reduce' })
                return `${x.length} entrenos ajustados en los próximos ${d} días.`
              })}>Reducir {d} d</button>
            ))}
            <button className="btn btn-sm" disabled={busy} onClick={() => run(async () => {
              const x = await api.post<unknown[]>('/api/not-feeling-100', { days: 3, mode: 'rest' })
              return `${x.length} entrenos pasados a regenerativo.`
            })}>Descanso 3 d</button>
          </div>
        </div>
      )}
      {msg && <div style={{ marginTop: 10, whiteSpace: 'pre-wrap' }}><Banner tone={msg.startsWith('Error') ? 'bad' : 'info'}>{msg}</Banner></div>}
    </div>
  )
}

function WeatherChip({ date, w, onAdjusted }: { date: string; w: Workout; onAdjusted: () => void }) {
  const { data } = useApi<Weather>(`/api/weather?date=${date}`)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  if (!data || data.available === false || w.sport !== 'running') return null
  const heated = !!(w as Workout & { _heat?: unknown })._heat
  return (
    <div style={{ marginTop: 12 }}>
      <div className="row">
        <span className={`chip ${data.pct >= 1 ? 'chip-warn' : ''}`} title={`Temperatura + punto de rocío = ${data.sum_f} °F`}>
          <Icon name="sun" size={14} />{Math.round(data.temp)} °C · rocío {Math.round(data.dew)} °C a las {data.hour}h
          {data.pct >= 1 ? ` · ritmo +${data.pct}%` : ''}
        </span>
        {data.pct >= 1 && !heated && (
          <button className="btn btn-sm" disabled={busy} onClick={async () => {
            setBusy(true)
            try {
              const r = await api.post<{ changes: unknown[]; pushed: number }>('/api/heat/apply')
              setMsg(`${r.changes.length} entrenos ajustados por calor${r.pushed ? `, ${r.pushed} actualizados en el reloj` : ''}.`)
              onAdjusted()
            } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
          }}>Ajustar por calor</button>
        )}
        {heated && <span className="chip chip-good"><Icon name="check" size={13} />Ajustado por calor</span>}
      </div>
      {data.too_hot && <div style={{ marginTop: 8 }}><Banner>Calor extremo: hazla a primera hora, en cinta o cámbiala por un rodaje suave. Hidrátate antes y durante.</Banner></div>}
      {msg && <div className="small muted" style={{ marginTop: 6 }}>{msg}</div>}
    </div>
  )
}

function Hero({ w, date, onOpen, onPushed }: { w: Workout | null; date: string; onOpen: (w: Workout) => void; onPushed: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [an, setAn] = useState(false)
  const today = iso(new Date())
  const label = date === today ? 'Hoy' : fmtDate(date, { weekday: 'long', day: 'numeric', month: 'short' })
  if (!w)
    return (
      <div className="card hero" style={{ ['--hero-zone' as string]: 'var(--z0)' }}>
        <div className="micro">{label}</div>
        <h2 style={{ marginTop: 6 }}>Descanso</h2>
        <p className="text-2" style={{ marginTop: 6 }}>Dormir bien y comer suficiente también es entrenar. La adaptación ocurre en la recuperación.</p>
      </div>
    )
  const lvl = workoutLevel(w)
  return (
    <div className="card hero" style={{ ['--hero-zone' as string]: zoneVar(lvl) }}>
      <div className="row spread">
        <span className="micro">{label}</span>
        <div className="row">
          {w.status === 'done' && <span className="chip chip-good"><Icon name="check" size={14} />Completado</span>}
          {w.status === 'modified' && <span className="chip chip-warn">Ajustado</span>}
          {w.extra && <span className="chip chip-outline">Opcional</span>}
        </div>
      </div>
      <h2 style={{ marginTop: 6, fontSize: 28, lineHeight: '34px' }}>{w.title}</h2>
      <div className="text-2 num" style={{ marginTop: 4 }}><WorkoutMeta w={w} /> · Z{lvl}</div>
      {w.sport === 'running' && <div style={{ marginTop: 16 }}><StepProfile steps={w.steps} /></div>}
      {w.status !== 'done' && date >= iso(new Date()) && daysBetween(iso(new Date()), date) <= 2 && <WeatherChip date={date} w={w} onAdjusted={onPushed} />}
      {w.note && <div style={{ marginTop: 12 }}><Banner>{w.note}</Banner></div>}
      <details style={{ marginTop: 12 }}>
        <summary className="small">Pasos y explicación</summary>
        <p className="small text-2" style={{ marginTop: 8 }}>{w.description}</p>
        {w.sport === 'running' && <Steps steps={w.steps} />}
      </details>
      <div className="row" style={{ marginTop: 16 }}>
        {w.status === 'done' && w.activity_id
          ? <button className="btn btn-primary" onClick={() => setAn(true)}><Icon name="activity" />Real vs plan</button>
          : <button className="btn btn-primary" onClick={() => onOpen(w)}>Ver detalle</button>}
        {w.status === 'done' && w.activity_id && <button className="btn" onClick={() => onOpen(w)}>Ver entreno</button>}
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
            <Icon name={w.garmin_workout_id ? 'check' : 'watch'} />{w.garmin_workout_id ? 'En el reloj' : busy ? 'Enviando…' : 'Enviar al reloj'}
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
    <div className="weekstrip" role="group" aria-label="Semana">
      {DAY_NAMES.map((dn, i) => {
        const d = addDays(monday, i)
        const ws = (byDate.get(d) ?? []).filter((w) => w.status !== 'skipped')
        const runs = ws.filter((w) => w.sport === 'running')
        const done = runs.length > 0 && runs.every((w) => w.status === 'done')
        return (
          <button key={d} className={`daycell ${d === today ? 'today' : ''}`} aria-pressed={d === sel} onClick={() => onSel(d)}
            aria-label={`${fmtDate(d, { weekday: 'long', day: 'numeric' })}: ${ws.map((w) => w.title).join(', ') || 'descanso'}`}>
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
  if (loading && !data) return <div className="card"><div className="micro">Semana pasada</div><Skeleton h={60} style={{ marginTop: 10 }} /></div>
  if (!data) return null
  const f = data.facts
  const end = addDays(data.week_start, 6)
  return (
    <div className="card">
      <div className="row spread">
        <div className="micro">Semana pasada · {fmtDate(data.week_start, { day: 'numeric', month: 'short' })}–{fmtDate(end, { day: 'numeric', month: 'short' })}</div>
        <button className="btn btn-ghost btn-icon btn-sm" aria-label="Regenerar resumen" disabled={busy} onClick={async () => {
          setBusy(true)
          try { setData(await api.post<Review>('/api/weekly-review')) } finally { setBusy(false) }
        }}><Icon name="refresh" size={16} className={busy ? 'spin' : ''} /></button>
      </div>
      <div className="mini-stats" style={{ marginTop: 10 }}>
        <div><span className="micro">Km</span><b>{f.km}{f.km_plan ? <small> / {f.km_plan}</small> : null}</b></div>
        <div><span className="micro">Sesiones</span><b>{f.sesiones_plan ? `${f.hechas}/${f.sesiones_plan}` : f.carreras}</b></div>
        <div><span className="micro">Forma (CTL)</span><b>{f.carga.ctl ?? '–'}{f.carga.ctl_cambio ? <small> {f.carga.ctl_cambio > 0 ? '+' : ''}{f.carga.ctl_cambio}</small> : null}</b></div>
        <div><span className="micro">ACWR</span><b>{f.carga.acwr ?? '–'}</b></div>
      </div>
      <p className="text-2" style={{ marginTop: 12, marginBottom: 0, whiteSpace: 'pre-wrap' }}>{data.comment}</p>
      {data.ai && <div className="small muted" style={{ marginTop: 6 }}><Icon name="sparkles" size={13} /> Comentario del coach IA</div>}
    </div>
  )
}

function RaceSoonCard({ r }: { r: Race }) {
  return (
    <a className="card race-soon" href={`#carreras/estrategia/${r.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
      <div className="row spread" style={{ flexWrap: 'nowrap' }}>
        <div style={{ minWidth: 0 }}>
          <div className="micro">{r.days_to_go === 0 ? '¡Hoy es el día!' : r.days_to_go === 1 ? 'Mañana' : `En ${r.days_to_go} días`}</div>
          <div style={{ fontWeight: 700, fontSize: 18, marginTop: 4 }}>🏁 {r.name}</div>
          <div className="small muted">{r.strategy_target_s ? `Objetivo ${fmtTime(r.strategy_target_s)} · ` : ''}Ritmo km a km, desnivel, tiempo y avituallamiento</div>
        </div>
        <span className="btn btn-primary btn-sm" style={{ flex: 'none' }}>Estrategia<Icon name="chevronRight" size={16} /></span>
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
          {weekNow && plan && <div className="small muted">Semana {weekNow.index}/{plan.weeks.length} · {PHASE_LABEL[weekNow.phase] ?? weekNow.phase}{weekNow.is_recovery ? ' · descarga' : ''}</div>}
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
          <Empty icon="calendar" title="Sin plan activo">Crea un plan basado en tu objetivo o pídeselo al coach.</Empty>
          <div className="row" style={{ justifyContent: 'center' }}>
            <button className="btn btn-primary" onClick={() => go('plan')}>Crear plan</button>
            <button className="btn" onClick={() => go('coach')}>Hablar con el coach</button>
          </div>
        </div>
      ) : (
        <>
          {!started && (
            <div className="card">
              <div className="row spread">
                <div>
                  <div className="micro">Antes del plan</div>
                  <div style={{ fontWeight: 600, marginTop: 4 }}>Tu plan «{plan.name}» empieza el {fmtDate(plan.start_date, { weekday: 'long', day: 'numeric', month: 'long' })} (en {daysBetween(today, plan.start_date)} días).</div>
                  <div className="small muted">Hasta entonces sigue tu plan actual. Aquí ves la primera semana.</div>
                </div>
                <button className="btn" onClick={() => go('plan')}>Ver plan<Icon name="chevronRight" size={16} /></button>
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
                  <span className="micro">{weekNow ? 'Esta semana' : 'Semana 1 del plan'}</span>
                  {focusWeek && <span className="small muted num">{focusWeek.done_km} / {focusWeek.planned_km} km</span>}
                </div>
                <WeekStrip monday={monday} byDate={byDate} sel={selDay} onSel={setSel} />
              </div>
            </div>
            <ReadinessCard onChanged={reload} />
          </div>
        </>
      )}
      <WeeklyReviewCard />
      {pick && <WorkoutDetail w={pick} onClose={() => setPick(null)} onChange={reload} />}
    </div>
  )
}
