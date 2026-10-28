import { useState } from 'react'
import { api, fmtDate, fmtKm, fmtTime, iso, useApi, type Plan, type Race } from '../api'
import { Banner, Empty, Icon, Segmented, Sheet, Skeleton } from '../ui'
import { PlanForm } from './PlanPage'
import RaceStrategy from '../components/RaceStrategy'

type CalItem = { external_id: string; name: string; date: string | null; status: string; url: string; running: boolean }
type CalEvent = { external_id: string; url: string; date: string | null; time: string | null; location: string | null; price: string | null; route: string | null; distances_km: number[] }
type AddResult = Race & { changes: string[]; recovery_days?: number; suggestion?: string | null }
type Prio = 'A' | 'B' | 'C'

const PRIO_HELP: Record<Prio, string> = {
  A: 'Objetivo principal: el plan se periodiza y afina hacia ella.',
  B: 'Preparatoria: mini-taper de 3 días y recuperación (~1 día suave por cada 3 km).',
  C: 'De entreno: sin taper, cuenta como sesión de calidad; solo el día siguiente suave.',
}
const goalFor = (m?: number | null) => (!m ? '10k' : m < 7500 ? '5k' : m < 15000 ? '10k' : m < 30000 ? 'half' : 'marathon')

function DateBox({ d }: { d: string }) {
  return (
    <div className="datebox" aria-hidden>
      <b>{+d.slice(8)}</b>
      <span>{fmtDate(d, { month: 'short' }).replace('.', '')}</span>
    </div>
  )
}

function AddRaceSheet({ onClose, onAdded }: { onClose: () => void; onAdded: (r: AddResult) => void }) {
  const [mode, setMode] = useState<'search' | 'manual'>('search')
  const [q, setQ] = useState('')
  const cal = useApi<CalItem[]>('/api/race-calendar')
  const [sel, setSel] = useState<CalItem | null>(null)
  const [ev, setEv] = useState<CalEvent | null>(null)
  const [form, setForm] = useState({ name: '', date: '', km: '', priority: 'B' as Prio, location: '', goal_time: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }))

  const choose = async (it: CalItem) => {
    setSel(it)
    setEv(null)
    setForm((f) => ({ ...f, name: it.name, date: it.date ?? '', km: '' }))
    try {
      const e = await api.get<CalEvent>(`/api/race-calendar/${it.external_id.split(':')[1]}`)
      setEv(e)
      setForm((f) => ({ ...f, km: e.distances_km[0] ? String(e.distances_km[0]) : '', location: e.location ?? '' }))
    } catch (e) { setErr((e as Error).message) }
  }
  const save = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.post<AddResult>('/api/races', {
        name: form.name, date: form.date, distance_m: form.km ? Math.round(+form.km * 1000) : undefined, priority: form.priority,
        location: form.location || undefined, goal_time: form.goal_time || undefined,
        ...(sel ? { url: sel.url, source: 'orycron', external_id: sel.external_id } : { source: 'manual' }),
      })
      onAdded(r)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const list = (cal.data ?? []).filter((i) => !q || i.name.toLowerCase().includes(q.toLowerCase()))
  const showForm = mode === 'manual' || sel

  return (
    <Sheet title="Añadir carrera" onClose={onClose} labelledBy="addrace-title">
      {!sel && <Segmented label="Origen" value={mode} onChange={setMode} options={[['search', 'Buscar en Orycron'], ['manual', 'Manual']]} />}
      {mode === 'search' && !sel && (
        <div style={{ marginTop: 14 }}>
          <label className="field">Buscar
            <input type="search" placeholder="Nombre de la carrera…" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <div className="small muted" style={{ margin: '8px 0' }}>Fuente: <a href="https://www.orycronsport.com/competiciones/?proximas=1" target="_blank" rel="noreferrer">Orycron Sport</a> · Salamanca y alrededores · solo carreras a pie</div>
          {cal.loading ? <><Skeleton h={56} /><Skeleton h={56} style={{ marginTop: 8 }} /></> : cal.error ? <Banner tone="bad">{cal.error}</Banner> : (
            <div className="list">
              {list.map((it) => (
                <button key={it.external_id} className="list-row" onClick={() => choose(it)}>
                  {it.date && <DateBox d={it.date} />}
                  <div className="grow"><div className="title">{it.name}</div><div className="meta">{it.status}</div></div>
                  <Icon name="plus" />
                </button>
              ))}
              {list.length === 0 && <Empty icon="search" title="Sin resultados" />}
            </div>
          )}
        </div>
      )}
      {showForm && (
        <div style={{ marginTop: 14 }}>
          {sel && (
            <div className="row spread" style={{ marginBottom: 12 }}>
              <button className="btn btn-ghost btn-sm" onClick={() => { setSel(null); setEv(null) }}>← Volver</button>
              <a className="small" href={sel.url} target="_blank" rel="noreferrer">Ver en Orycron <Icon name="external" size={13} /></a>
            </div>
          )}
          {sel && !ev && <Skeleton h={18} w="60%" />}
          {ev && <div className="small text-2" style={{ marginBottom: 12 }}>{[ev.location, ev.time, ev.route && `Recorrido: ${ev.route}`, ev.price].filter(Boolean).join(' · ')}</div>}
          <div className="form-grid">
            <label className="field">Nombre<input value={form.name} onChange={(e) => set('name', e.target.value)} /></label>
            <label className="field">Fecha<input type="date" value={form.date} min={iso(new Date())} onChange={(e) => set('date', e.target.value)} /></label>
            <label className="field">Distancia (km)
              <input type="number" step="0.001" inputMode="decimal" value={form.km} onChange={(e) => set('km', e.target.value)} />
            </label>
            <label className="field">Objetivo (opcional)<input placeholder="45:00" value={form.goal_time} onChange={(e) => set('goal_time', e.target.value)} /></label>
          </div>
          {ev && ev.distances_km.length > 1 && (
            <div className="row" style={{ marginTop: 10 }}>
              <span className="small muted">Distancias:</span>
              {ev.distances_km.map((k) => <button key={k} className={`btn btn-sm ${+form.km === k ? 'btn-primary' : ''}`} onClick={() => set('km', String(k))}>{k} km</button>)}
            </div>
          )}
          <div style={{ marginTop: 14 }}>
            <div className="field" style={{ marginBottom: 6 }}>Prioridad</div>
            <Segmented label="Prioridad" value={form.priority} onChange={(v) => set('priority', v)} options={[['A', 'A · Objetivo'], ['B', 'B · Preparatoria'], ['C', 'C · Entreno']]} />
            <p className="small muted" style={{ marginTop: 6 }}>{PRIO_HELP[form.priority]}</p>
          </div>
          {err && <Banner tone="bad">{err}</Banner>}
          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}>
            <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
            <button className="btn btn-primary" disabled={busy || !form.name || !form.date} onClick={save}><Icon name="flag" />Añadir al plan</button>
          </div>
        </div>
      )}
    </Sheet>
  )
}

function RaceDetail({ r, onClose, onChange, onPlan, onStrategy }: { r: Race; onClose: () => void; onChange: () => void; onPlan: (r: Race) => void; onStrategy: (r: Race) => void }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad' | 'info'; text: string } | null>(null)
  const [result, setResult] = useState('')
  const [confirm, setConfirm] = useState(false)
  const past = r.days_to_go < 0
  const update = async (body: Record<string, unknown>) => {
    setBusy(true)
    try {
      const x = await api.put<AddResult>(`/api/races/${r.id}`, body)
      setMsg({ tone: 'ok', text: x.changes.length ? `Plan reajustado:\n${x.changes.join('\n')}` : 'Guardado' })
      onChange()
    } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) } finally { setBusy(false) }
  }
  return (
    <Sheet title={r.name} onClose={onClose} labelledBy="race-title">
      <div className="row small" style={{ marginBottom: 12 }}>
        <span className="chip">{fmtDate(r.date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</span>
        {r.distance_m && <span className="chip">{fmtKm(r.distance_m)}</span>}
        {r.location && <span className="chip">{r.location}</span>}
        {!past && <span className="chip chip-accent">{r.days_to_go === 0 ? '¡Hoy!' : `Faltan ${r.days_to_go} días`}</span>}
        {r.goal_time_s && <span className="chip">Objetivo {fmtTime(r.goal_time_s)}</span>}
        {r.result_time_s && <span className="chip chip-good">Resultado {fmtTime(r.result_time_s)}</span>}
      </div>
      {!past && (
        <>
          <button className="btn btn-primary btn-block" style={{ marginBottom: 14 }} onClick={() => onStrategy(r)}><Icon name="zap" />Estrategia de carrera: ritmo km a km</button>
          <div className="field" style={{ marginBottom: 6 }}>Prioridad</div>
          <Segmented label="Prioridad" value={r.priority} onChange={(v) => update({ priority: v })} options={[['A', 'A · Objetivo'], ['B', 'B · Preparatoria'], ['C', 'C · Entreno']]} />
          <p className="small muted" style={{ marginTop: 6 }}>{PRIO_HELP[r.priority]}</p>
          {r.priority === 'A' && <button className="btn" onClick={() => onPlan(r)}><Icon name="calendar" />Crear plan hacia esta carrera</button>}
        </>
      )}
      {past && (
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <label className="field grow" style={{ maxWidth: 200 }}>Tu tiempo<input placeholder="h:mm:ss" value={result} onChange={(e) => setResult(e.target.value)} /></label>
          <button className="btn btn-primary" disabled={busy || !result} onClick={() => update({ result_time: result })}>Guardar resultado</button>
        </div>
      )}
      {r.url && <p className="small" style={{ marginTop: 12 }}><a href={r.url} target="_blank" rel="noreferrer">Información e inscripción <Icon name="external" size={13} /></a></p>}
      {msg && <div style={{ marginTop: 12, whiteSpace: 'pre-wrap' }}><Banner tone={msg.tone}>{msg.text}</Banner></div>}
      <hr />
      {!confirm ? <button className="btn btn-danger" onClick={() => setConfirm(true)}><Icon name="trash" />Quitar carrera</button> : (
        <div className="row">
          <span className="small">Se deshacen los ajustes del plan. ¿Quitar?</span>
          <button className="btn btn-danger" disabled={busy} onClick={async () => { await api.del(`/api/races/${r.id}`); onChange(); onClose() }}>Sí, quitar</button>
          <button className="btn btn-ghost" onClick={() => setConfirm(false)}>No</button>
        </div>
      )}
    </Sheet>
  )
}

export default function RacesPage({ plan, reload }: { plan: Plan | null; reload: () => void }) {
  const { data, loading, reload: reloadRaces } = useApi<Race[]>('/api/races')
  const [adding, setAdding] = useState(false)
  const [open, setOpen] = useState<Race | null>(null)
  const [planFor, setPlanFor] = useState<Race | null>(null)
  const [last, setLast] = useState<AddResult | null>(null)
  const [strategy, setStrategy] = useState<Race | null>(() => {
    const m = window.location.hash.match(/^#carreras\/estrategia\/(\d+)/)
    return m ? ({ id: +m[1] } as Race) : null
  })
  const changed = () => { reloadRaces(); reload() }
  const upcoming = (data ?? []).filter((r) => r.days_to_go >= 0)
  const past = (data ?? []).filter((r) => r.days_to_go < 0).reverse()
  const planWeek = (d: string) => plan?.weeks.find((w) => w.start <= d && d <= w.end)?.index

  if (strategy) return <RaceStrategy race={strategy} onBack={() => { setStrategy(null); if (window.location.hash.includes('/')) window.location.hash = 'carreras' }} />
  return (
    <div className="stack">
      <div className="row spread">
        <p className="text-2" style={{ margin: 0, maxWidth: 560 }}>Apunta las carreras de tu preparación. OpenRun ajusta el plan alrededor de cada una según su prioridad.</p>
        <button className="btn btn-primary" onClick={() => setAdding(true)}><Icon name="search" />Buscar carrera</button>
      </div>
      {last && (
        <Banner tone="ok">
          <strong>{last.name}</strong> añadida ({last.priority}).
          {last.changes.length > 0 && <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{last.changes.map((c) => <li key={c}>{c}</li>)}</ul>}
          {last.suggestion && <div style={{ marginTop: 6 }}>{last.suggestion}</div>}
        </Banner>
      )}
      <div className="card">
        <div className="card-head"><span className="micro">Próximas</span></div>
        {loading && !data ? <Skeleton h={56} /> : upcoming.length === 0 ? (
          <Empty icon="flag" title="Ninguna carrera apuntada">Busca en el calendario de Orycron o añádela a mano.</Empty>
        ) : (
          <div className="list">
            {upcoming.map((r) => (
              <button key={r.id} className="list-row" onClick={() => setOpen(r)}>
                <DateBox d={r.date} />
                <div className="grow">
                  <div className="title">{r.name}</div>
                  <div className="meta">
                    {[fmtKm(r.distance_m), r.location, planWeek(r.date) ? `semana ${planWeek(r.date)} del plan` : null].filter(Boolean).join(' · ')}
                  </div>
                </div>
                <div className="right">
                  <span className={`prio prio-${r.priority}`} aria-label={`Prioridad ${r.priority}`}>{r.priority}</span>
                  <div className="small muted num" style={{ marginTop: 4 }}>{r.days_to_go} d</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
      {past.length > 0 && (
        <div className="card">
          <div className="card-head"><span className="micro">Pasadas</span></div>
          <div className="list">
            {past.map((r) => (
              <button key={r.id} className="list-row" onClick={() => setOpen(r)}>
                <DateBox d={r.date} />
                <div className="grow"><div className="title">{r.name}</div><div className="meta">{fmtKm(r.distance_m)}</div></div>
                <div className="right big-time">{fmtTime(r.result_time_s)}</div>
              </button>
            ))}
          </div>
        </div>
      )}
      {adding && <AddRaceSheet onClose={() => setAdding(false)} onAdded={(r) => { setAdding(false); setLast(r); changed() }} />}
      {open && <RaceDetail r={open} onClose={() => setOpen(null)} onChange={changed} onPlan={(r) => { setOpen(null); setPlanFor(r) }} onStrategy={(r) => { setOpen(null); setStrategy(r); window.scrollTo(0, 0) }} />}
      {planFor && (
        <Sheet title={`Plan hacia ${planFor.name}`} onClose={() => setPlanFor(null)} labelledBy="pf-title">
          <Banner tone="info">Esto sustituye tu plan activo{plan ? ` («${plan.name}»)` : ''}.</Banner>
          <div style={{ marginTop: 12 }}>
            <PlanForm initial={{ goal: goalFor(planFor.distance_m), race_date: planFor.date }} onCreated={() => { setPlanFor(null); changed() }} onCancel={() => setPlanFor(null)} />
          </div>
        </Sheet>
      )}
    </div>
  )
}
