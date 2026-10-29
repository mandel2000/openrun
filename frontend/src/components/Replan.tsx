import { useState } from 'react'
import { api, fmtDate, useApi } from '../api'
import { Banner, Icon } from '../ui'

// Missed sessions and breaks: the plan adapts instead of leaving holes (see backend training/replan.py).
type Missed = { id: number; date: string; title: string; key: boolean; slot: { date: string; replaces_id: number | null; replaces_title: string | null } | null }
type Check = { missed: Missed[]; days_since_run: number | null; suggest_break: boolean }
type BreakRes = { changed: number; vdot: number; notes: string[]; rebuild: boolean; easy_days: number }

const day = (d: string) => fmtDate(d, { weekday: 'long', day: 'numeric' })

export function BreakForm({ initialDays, onDone }: { initialDays?: number | null; onDone: (msg: string) => void }) {
  const [days, setDays] = useState(String(initialDays ?? 5))
  const [reason, setReason] = useState('illness')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  return (
    <form className="stack" style={{ gap: 10 }} onSubmit={async (e) => {
      e.preventDefault()
      setBusy(true)
      setErr(null)
      try {
        const r = await api.post<BreakRes>('/api/replan/break', { days: +days, reason })
        onDone(`Plan ajustado: ${r.changed} entrenos de vuelta progresiva (${r.easy_days} días solo suave). ${r.notes.join(' ')}${r.rebuild ? ' Tras tanto tiempo, mejor crea un plan nuevo desde tu forma actual (Plan › Nuevo plan).' : ''}`)
      } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
    }}>
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="field" style={{ width: 120 }}>Días parado<input type="number" min={1} max={120} inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></label>
        <label className="field grow">Motivo
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="illness">Enfermedad</option><option value="injury">Lesión / molestia</option><option value="travel">Viaje / trabajo</option><option value="other">Otro</option>
          </select>
        </label>
      </div>
      <p className="small muted" style={{ margin: 0 }}>Cierra los entrenos que no hiciste, ajusta ritmos si llevas más de 5 días sin correr y hace la vuelta progresiva (primero solo suave, luego menos volumen).</p>
      <div className="row"><button className="btn btn-primary btn-sm" disabled={busy || !+days}>Ajustar el plan</button>{err && <span className="err small">{err}</span>}</div>
    </form>
  )
}

export function ReplanCard({ onChanged }: { onChanged: () => void }) {
  const { data, reload } = useApi<Check>('/api/replan')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [brk, setBrk] = useState(false)
  if (!data) return null
  const keys = data.missed.filter((m) => m.key)
  if (!keys.length && !data.suggest_break && !msg) return null
  const act = async (id: number, accept: boolean) => {
    setBusy(true)
    try {
      const r = await api.post<Check & { message: string }>('/api/replan', { workout_id: id, accept })
      setMsg(r.message); reload(); onChanged()
    } catch (e) { setMsg(`Error: ${(e as Error).message}`) } finally { setBusy(false) }
  }
  return (
    <div className="card">
      <div className="card-head"><span className="micro">Ajustes del plan</span><Icon name="calendar" size={18} /></div>
      {data.suggest_break && !brk && (
        <div className="stack" style={{ gap: 8 }}>
          <div><b>Llevas {data.days_since_run} días sin correr.</b> <span className="text-2">¿Has estado parado? Reajusto la vuelta para que no retomes donde lo dejaste.</span></div>
          <div className="row"><button className="btn btn-sm btn-primary" onClick={() => setBrk(true)}>Sí, ajustar</button></div>
        </div>
      )}
      {brk && <BreakForm initialDays={data.days_since_run} onDone={(m) => { setMsg(m); setBrk(false); reload(); onChanged() }} />}
      {keys.map((m) => (
        <div key={m.id} className="stack" style={{ gap: 6, marginTop: 10 }}>
          <div>No hiciste <b>«{m.title}»</b> ({day(m.date)}).</div>
          {m.slot ? (
            <>
              <div className="small text-2">Puedo pasarla al <b>{day(m.slot.date)}</b>{m.slot.replaces_title ? <> en lugar de «{m.slot.replaces_title}»</> : ''}, sin juntar dos días duros.</div>
              <div className="row">
                <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => act(m.id, true)}>Recolocar</button>
                <button className="btn btn-sm" disabled={busy} onClick={() => act(m.id, false)}>Dejarla pasar</button>
              </div>
            </>
          ) : (
            <div className="row">
              <span className="small text-2 grow">No hay hueco esta semana sin juntar sesiones duras: mejor dejarla pasar.</span>
              <button className="btn btn-sm" disabled={busy} onClick={() => act(m.id, false)}>Vale</button>
            </div>
          )}
        </div>
      ))}
      {msg && <div style={{ marginTop: 10 }}><Banner tone={msg.startsWith('Error') ? 'bad' : 'ok'}>{msg}</Banner></div>}
    </div>
  )
}
