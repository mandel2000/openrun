import { useState } from 'react'
import { api, fmtDate, useApi } from '../api'
import { Banner, Icon } from '../ui'
import { t } from '../i18n'

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
        onDone(`${t('Plan adjusted: {n} return-to-running workouts ({d} easy-only days).', { n: r.changed, d: r.easy_days })} ${r.notes.join(' ')}${r.rebuild ? ` ${t('After such a long break, better create a new plan from your current fitness (Plan › New plan).')}` : ''}`)
      } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
    }}>
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="field" style={{ width: 120 }}>{t('Days off')}<input type="number" min={1} max={120} inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></label>
        <label className="field grow">Motivo
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="illness">{t('Illness')}</option><option value="injury">{t('Injury / niggle')}</option><option value="travel">{t('Travel / work')}</option><option value="other">{t('Other')}</option>
          </select>
        </label>
      </div>
      <p className="small muted" style={{ margin: 0 }}>{t('Closes the workouts you didn\'t do, adjusts paces if you\'ve been off for more than 5 days and builds a gradual return (easy running first, then reduced volume).')}</p>
      <div className="row"><button className="btn btn-primary btn-sm" disabled={busy || !+days}>{t('Adjust the plan')}</button>{err && <span className="err small">{err}</span>}</div>
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
      <div className="card-head"><span className="micro">{t('Plan adjustments')}</span><Icon name="calendar" size={18} /></div>
      {data.suggest_break && !brk && (
        <div className="stack" style={{ gap: 8 }}>
          <div><b>{t('You haven’t run for {n} days.', { n: data.days_since_run ?? 0 })}</b> <span className="text-2">{t('Have you had a break? I’ll adjust your return so you don’t pick up where you left off.')}</span></div>
          <div className="row"><button className="btn btn-sm btn-primary" onClick={() => setBrk(true)}>{t('Yes, adjust')}</button></div>
        </div>
      )}
      {brk && <BreakForm initialDays={data.days_since_run} onDone={(m) => { setMsg(m); setBrk(false); reload(); onChanged() }} />}
      {keys.map((m) => (
        <div key={m.id} className="stack" style={{ gap: 6, marginTop: 10 }}>
          <div>{t('You didn’t do')} <b>“{m.title}”</b> ({day(m.date)}).</div>
          {m.slot ? (
            <>
              <div className="small text-2">{t('I can move it to')} <b>{day(m.slot.date)}</b>{m.slot.replaces_title ? <> {t('instead of')} “{m.slot.replaces_title}”</> : ''}{t(', without two hard days in a row.')}</div>
              <div className="row">
                <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => act(m.id, true)}>{t('Reschedule')}</button>
                <button className="btn btn-sm" disabled={busy} onClick={() => act(m.id, false)}>{t('Let it go')}</button>
              </div>
            </>
          ) : (
            <div className="row">
              <span className="small text-2 grow">{t('No slot this week without stacking hard sessions: better let it go.')}</span>
              <button className="btn btn-sm" disabled={busy} onClick={() => act(m.id, false)}>{t('OK')}</button>
            </div>
          )}
        </div>
      ))}
      {msg && <div style={{ marginTop: 10 }}><Banner tone={msg.startsWith('Error') ? 'bad' : 'ok'}>{msg}</Banner></div>}
    </div>
  )
}
