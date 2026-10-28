import { useState } from 'react'
import { api, fmtDate, fmtDur, fmtPace, PHASE_LABEL, STATUS_LABEL, workoutLevel, ZONE_LABEL, zoneLevel, zoneVar, type Step, type Workout } from '../api'
import { ExerciseList, RoutineBlock } from './Exercises'
import { Banner, Icon, Sheet } from '../ui'
import StepProfile, { KIND } from './StepProfile'

function dur(s: Step) {
  if (s.duration_type === 'distance') return s.duration_value >= 1000 ? `${+(s.duration_value / 1000).toFixed(2)} km` : `${s.duration_value} m`
  if (s.duration_type === 'time') return s.duration_value >= 60 ? `${+(s.duration_value / 60).toFixed(1)}′` : `${s.duration_value}″`
  return 'hasta pulsar vuelta'
}

export function Steps({ steps, hl, prefix = '' }: { steps: Step[]; hl?: string | null; prefix?: string }) {
  return (
    <ul className="steps">
      {steps.map((s, i) => {
        const path = prefix + i
        if (s.kind === 'repeat')
          return (
            <li key={i} className="rep">
              <strong>{s.repeat}× repeticiones</strong>
              <Steps steps={s.steps ?? []} hl={hl} prefix={`${path}.`} />
            </li>
          )
        const lvl = s.kind === 'rest' ? 0 : s.zone ? zoneLevel(s.zone) : s.kind === 'recovery' ? 1 : 2
        return (
          <li key={i} className={hl === path ? 'hl' : ''}>
            <span className="stepbar" style={{ ['--zc' as string]: zoneVar(lvl) }} />
            <div className="grow">
              <div><strong>{KIND[s.kind]}</strong> · {dur(s)}{s.zone ? <span className="muted"> · {ZONE_LABEL[s.zone] ?? s.zone} (Z{lvl})</span> : null}</div>
              {s.pace_slow && s.pace_fast ? <div className="num" style={{ fontWeight: 600 }}>{fmtPace(s.pace_slow)}–{fmtPace(s.pace_fast)} /km</div> : null}
              {s.note ? <div className="muted small">{s.note}</div> : null}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export function WorkoutMeta({ w }: { w: Workout }) {
  return (
    <span className="num">
      {w.sport === 'running' ? `${w.distance_km} km · ${fmtDur(w.duration_min)}` : `${fmtDur(w.duration_min || 45)} · fuerza`}
    </span>
  )
}

export default function WorkoutDetail({ w, onClose, onChange }: { w: Workout; onClose: () => void; onChange: () => void }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [newDate, setNewDate] = useState(w.date)
  const [confirmDel, setConfirmDel] = useState(false)
  const [hl, setHl] = useState<string | null>(null)
  const lvl = workoutLevel(w)

  const act = async (fn: () => Promise<unknown>, ok: string, close = false) => {
    setBusy(true)
    setMsg(null)
    try {
      await fn()
      setMsg({ tone: 'ok', text: ok })
      onChange()
      if (close) onClose()
    } catch (e) {
      setMsg({ tone: 'bad', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet title={w.title} onClose={onClose} labelledBy="wd-title">
      <div className="row small text-2" style={{ marginBottom: 12 }}>
        <span className="chip"><span className="zbar" style={{ ['--zc' as string]: zoneVar(lvl) }} />{fmtDate(w.date, { weekday: 'long', day: 'numeric', month: 'long' })}</span>
        <span className="chip"><WorkoutMeta w={w} /></span>
        {w.phase && <span className="chip">{PHASE_LABEL[w.phase] ?? w.phase}</span>}
        <span className={`chip ${w.status === 'done' ? 'chip-good' : w.status === 'skipped' ? 'chip-bad' : w.status === 'modified' ? 'chip-warn' : ''}`}>{STATUS_LABEL[w.status] ?? w.status}</span>
        {w.extra && <span className="chip chip-outline">Opcional</span>}
        {w.garmin_workout_id && <span className="chip chip-good"><Icon name="watch" size={14} />En Garmin</span>}
      </div>
      {w.sport === 'running' && <StepProfile steps={w.steps} onHover={setHl} />}
      <p style={{ marginTop: 12 }} className="text-2">{w.description}</p>
      {w.note && <Banner>{w.note}</Banner>}
      {w.sport === 'running' && <Steps steps={w.steps} hl={hl} />}
      {w.sport === 'strength' && w.exercises && <ExerciseList items={w.exercises} storeKey={`ex-${w.id}`} />}
      {w.sport === 'running' && (w.intensity === 'high' || w.intensity === 'moderate' || w.type === 'race') && <RoutineBlock kind="warmup" />}
      {w.sport === 'running' && <RoutineBlock kind="mobility" />}

      <hr />
      <div className="row">
        {w.sport === 'running' && (
          <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.post('/api/garmin/push', { ids: [w.id] }).then((r) => {
            const res = (r as { ok: boolean; error?: string }[])[0]
            if (!res.ok) throw new Error(res.error)
          }), 'Enviado a Garmin Connect. Sincroniza el reloj.')}>
            <Icon name="watch" />{w.garmin_workout_id ? 'Reenviar al reloj' : 'Enviar al reloj'}
          </button>
        )}
        {w.sport === 'strength' && (
          <button className={`btn ${w.status === 'done' ? '' : 'btn-primary'}`} disabled={busy} onClick={() => act(() => api.post(`/api/workouts/${w.id}/done`), w.status === 'done' ? 'Desmarcada' : '¡Sesión hecha!')}>
            <Icon name="check" />{w.status === 'done' ? 'Desmarcar' : 'Marcar como hecha'}
          </button>
        )}
        <button className="btn" disabled={busy || w.status === 'skipped'} onClick={() => act(() => api.post(`/api/workouts/${w.id}/skip`), 'Marcado como no realizado')}>
          <Icon name="skip" />Saltar
        </button>
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <label className="field grow" style={{ maxWidth: 220 }}>Mover a
          <input type="date" value={newDate} onChange={(e) => setNewDate(e.target.value)} />
        </label>
        <button className="btn" style={{ alignSelf: 'flex-end' }} disabled={busy || newDate === w.date}
          onClick={() => act(() => api.post(`/api/workouts/${w.id}/move`, { date: newDate }), 'Movido' + (w.garmin_workout_id ? ' (y reprogramado en Garmin)' : ''))}>
          <Icon name="move" />Mover
        </button>
        <span className="grow" />
        {!confirmDel ? (
          <button className="btn btn-danger" style={{ alignSelf: 'flex-end' }} disabled={busy} onClick={() => setConfirmDel(true)}><Icon name="trash" />Eliminar</button>
        ) : (
          <div className="row" style={{ alignSelf: 'flex-end' }}>
            <span className="small">¿Seguro?</span>
            <button className="btn btn-danger" disabled={busy} onClick={() => act(() => api.del(`/api/workouts/${w.id}`), 'Eliminado', true)}>Sí, eliminar</button>
            <button className="btn btn-ghost" onClick={() => setConfirmDel(false)}>No</button>
          </div>
        )}
      </div>
      {msg && <div style={{ marginTop: 12 }}><Banner tone={msg.tone}>{msg.text}</Banner></div>}
    </Sheet>
  )
}
