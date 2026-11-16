import { useState } from 'react'
import { api, fmtDate, fmtDur, fmtPace, iso, PHASE_LABEL, STATUS_LABEL, useApi, workoutLevel, ZONE_LABEL, zoneLevel, zoneVar, type Step, type Workout } from '../api'
import { ExerciseList, RoutineBlock } from './Exercises'
import { Banner, Icon, Sheet, Skeleton } from '../ui'
import StepProfile, { KIND } from './StepProfile'
import { t } from '../i18n'

function dur(s: Step) {
  if (s.duration_type === 'distance') return s.duration_value >= 1000 ? `${+(s.duration_value / 1000).toFixed(2)} km` : `${s.duration_value} m`
  if (s.duration_type === 'time') return s.duration_value >= 60 ? `${+(s.duration_value / 60).toFixed(1)}′` : `${s.duration_value}″`
  return t('until lap button')
}

export function Steps({ steps, hl, prefix = '' }: { steps: Step[]; hl?: string | null; prefix?: string }) {
  return (
    <ul className="steps">
      {steps.map((s, i) => {
        const path = prefix + i
        if (s.kind === 'repeat')
          return (
            <li key={i} className="rep">
              <strong>{s.repeat}× {t('repeats')}</strong>
              <Steps steps={s.steps ?? []} hl={hl} prefix={`${path}.`} />
            </li>
          )
        const lvl = s.kind === 'rest' ? 0 : s.zone ? zoneLevel(s.zone) : s.kind === 'recovery' ? 1 : 2
        return (
          <li key={i} className={hl === path ? 'hl' : ''}>
            <span className="stepbar" style={{ ['--zc' as string]: zoneVar(lvl) }} />
            <div className="grow">
              <div><strong>{KIND[s.kind]}</strong> · {dur(s)}{s.zone ? <span className="muted"> · {ZONE_LABEL[s.zone] ?? s.zone}</span> : null}</div>
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
      {w.sport === 'running' ? `${w.distance_km} km · ${fmtDur(w.duration_min)}` : `${fmtDur(w.duration_min || 45)} · ${t('strength')}`}
    </span>
  )
}

type Alt = Pick<Workout, 'type' | 'title' | 'description' | 'intensity' | 'distance_km' | 'duration_min' | 'steps'> & { key: string; same_stimulus: boolean }

/** Other sessions that can take this one's place: same stimulus first, an easier option last. */
function SwapList({ w, busy, onPick }: { w: Workout; busy: boolean; onPick: (a: Alt) => void }) {
  const alts = useApi<Alt[]>(`/api/workouts/${w.id}/alternatives`)
  if (alts.error) return <Banner tone="bad">{alts.error}</Banner>
  if (!alts.data) return <Skeleton h={120} />
  if (!alts.data.length) return <p className="small muted">{t('There are no alternatives for this workout.')}</p>
  return (
    <div className="stack" style={{ gap: 8 }}>
      <p className="small text-2" style={{ margin: 0 }}>{t('Pick another session for that day. The first ones train the same thing in a different format; the week\'s load stays about the same.')}</p>
      {alts.data.map((a) => (
        <button key={a.key} className="altcard" disabled={busy} style={{ ['--zc' as string]: zoneVar(workoutLevel({ ...a, sport: 'running' })) }} onClick={() => onPick(a)}>
          <span className="row spread" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
            <strong style={{ overflowWrap: 'anywhere' }}>{a.title}</strong>
            <span className={`chip ${a.same_stimulus ? 'chip-good' : a.intensity === 'low' ? '' : 'chip-outline'}`} style={{ flexShrink: 0 }}>
              {a.same_stimulus ? t('Same goal') : a.intensity === 'low' ? t('Easier') : t('Similar')}
            </span>
          </span>
          <span className="num small muted">{a.distance_km} km · {fmtDur(a.duration_min)}</span>
          <span className="small text-2 clamp3">{a.description}</span>
        </button>
      ))}
    </div>
  )
}

export default function WorkoutDetail({ w: initial, onClose, onChange }: { w: Workout; onClose: () => void; onChange: () => void }) {
  const [w, setW] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad' | 'info'; text: string } | null>(null)
  const [newDate, setNewDate] = useState(w.date)
  const [confirmDel, setConfirmDel] = useState(false)
  const [swapping, setSwapping] = useState(false)
  const [hl, setHl] = useState<string | null>(null)
  const lvl = workoutLevel(w)
  const open = w.status !== 'done'
  const canSwap = open && w.sport === 'running' && !w.race_id && w.type !== 'race' && w.type !== 'shakeout'

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
  const swap = async (a: Alt) => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await api.post<Workout & { warnings: string[]; watch: { ok: number; failed: number } }>(`/api/workouts/${w.id}/swap`, { key: a.key })
      setW(r)
      setSwapping(false)
      setMsg({ tone: r.watch.failed ? 'bad' : r.warnings.length ? 'info' : 'ok',
        text: [t('Changed to “{title}”', { title: r.title }), r.watch.failed ? t('Could not update the watch (reconnect Garmin in Settings)') : r.watch.ok ? t('Watch updated') : '', ...r.warnings].filter(Boolean).join(' · ') })
      onChange()
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
        {w.extra && <span className="chip chip-outline">{t('Optional')}</span>}
        {w.garmin_workout_id && <span className="chip chip-good"><Icon name="watch" size={14} />{t('On Garmin')}</span>}
      </div>
      {swapping ? (
        <>
          <SwapList w={w} busy={busy} onPick={swap} />
          <div className="actions" style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => setSwapping(false)}>{t('Keep this workout')}</button>
          </div>
        </>
      ) : (
        <>
          {w.sport === 'running' && <StepProfile steps={w.steps} onHover={setHl} />}
          <p style={{ marginTop: 12 }} className="text-2">{w.description}</p>
          {w.swapped_from && <p className="small muted">{t('Replaces “{title}” from the original plan.', { title: w.swapped_from })}</p>}
          {w.note && <Banner>{w.note}</Banner>}
          {w.sport === 'running' && <Steps steps={w.steps} hl={hl} />}
          {w.sport === 'strength' && w.exercises && <ExerciseList items={w.exercises} storeKey={`ex-${w.id}`} />}
          {w.sport === 'running' && (w.intensity === 'high' || w.intensity === 'moderate' || w.type === 'race') && <RoutineBlock kind="warmup" />}
          {w.sport === 'running' && <RoutineBlock kind="mobility" />}

          <hr />
          <div className="actions">
            {w.sport === 'running' && (
              <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.post('/api/garmin/push', { ids: [w.id] }).then((r) => {
                const res = (r as { ok: boolean; error?: string }[])[0]
                if (!res.ok) throw new Error(res.error)
              }), t('Sent to Garmin Connect. Sync your watch.'))}>
                <Icon name="watch" />{w.garmin_workout_id ? t('Resend to watch') : t('Send to watch')}
              </button>
            )}
            {w.sport === 'strength' && (
              <button className={`btn ${w.status === 'done' ? '' : 'btn-primary'}`} disabled={busy} onClick={() => act(() => api.post(`/api/workouts/${w.id}/done`), w.status === 'done' ? t('Unmarked') : t('Session done!'))}>
                <Icon name="check" />{w.status === 'done' ? t('Unmark') : t('Mark as done')}
              </button>
            )}
            {canSwap && <button className="btn" disabled={busy} onClick={() => { setMsg(null); setSwapping(true) }}><Icon name="refresh" />{t('Change workout')}</button>}
            <button className="btn" disabled={busy || w.status === 'skipped'} onClick={() => act(() => api.post(`/api/workouts/${w.id}/skip`), t('Marked as skipped'))}>
              <Icon name="skip" />{t('Skip')}
            </button>
          </div>
          {open && (
            <div className="moverow">
              <label className="field">{t('Move to another day')}
                <input type="date" value={newDate} min={iso(new Date())} onChange={(e) => setNewDate(e.target.value)} />
              </label>
              <button className="btn" disabled={busy || !newDate || newDate === w.date}
                onClick={() => act(() => api.post(`/api/workouts/${w.id}/move`, { date: newDate }), t('Moved') + (w.garmin_workout_id ? ` ${t('(and rescheduled on Garmin)')}` : ''))}>
                <Icon name="move" />{t('Move')}
              </button>
            </div>
          )}
          <div className="actions" style={{ marginTop: 16 }}>
            {!confirmDel ? (
              <button className="btn btn-danger" disabled={busy} onClick={() => setConfirmDel(true)}><Icon name="trash" />{t('Delete')}</button>
            ) : (
              <>
                <button className="btn btn-danger" disabled={busy} onClick={() => act(() => api.del(`/api/workouts/${w.id}`), t('Deleted'), true)}>{t('Yes, delete')}</button>
                <button className="btn" onClick={() => setConfirmDel(false)}>{t('Cancel')}</button>
              </>
            )}
          </div>
        </>
      )}
      {msg && <div style={{ marginTop: 12 }}><Banner tone={msg.tone}>{msg.text}</Banner></div>}
    </Sheet>
  )
}
