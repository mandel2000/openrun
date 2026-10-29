import { useState } from 'react'
import { api, useApi, type Readiness, type Workout } from '../api'
import { Banner, Icon, Skeleton } from '../ui'
import { BreakForm } from './Replan'
import { t } from '../i18n'

// Daily readiness: 0-100 score from HRV, sleep, resting HR, load and a 2-question check-in. When it
// is low and today's session is hard, the app proposes a softer version; the athlete decides.
type View = {
  readiness: Readiness
  workout: Workout | null
  proposal: { workout_id: number; from: string; to: string; to_km: number; reason: string } | null
  checkin: { feel?: number; legs?: number; sick?: boolean } | null
  explanation: string | null
}
type WRow = { date: string; sleep_score?: number; rest_hr?: number; training_readiness?: number; body_battery?: number; hrv_rmssd?: number }

const RLABEL = { green: t('Ready to train'), amber: t('Moderate fatigue'), red: t('Recover today'), unknown: t('Not enough data') }
const RICON = { green: 'check', amber: 'alert', red: 'x', unknown: 'heart' } as const
const FEEL = [t('Awful'), t('Bad'), t('Normal'), t('Good'), t('Great')]
const LEGS = [t('Very heavy'), t('Heavy'), t('Normal'), t('Fresh'), t('Very fresh')]
const tone = (n: number) => (n >= 65 ? 'var(--good)' : n >= 45 ? 'var(--warn)' : 'var(--bad)')

function Scale({ label, opts, value, onPick }: { label: string; opts: string[]; value?: number; onPick: (v: number) => void }) {
  return (
    <div role="radiogroup" aria-label={label}>
      <div className="micro" style={{ marginBottom: 4 }}>{label}</div>
      <div className="scale">
        {opts.map((o, i) => (
          <button key={o} type="button" role="radio" aria-checked={value === i + 1} className={`scale-btn${value === i + 1 ? ' on' : ''}`} onClick={() => onPick(i + 1)}>
            <b>{i + 1}</b><span>{o}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export default function ReadinessCard({ onChanged }: { onChanged: () => void }) {
  const { data, loading, reload } = useApi<View>('/api/readiness')
  const rows = useApi<{ rows: WRow[] }>('/api/wellness?days=3')
  const [v, setV] = useState<View | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [more, setMore] = useState(false)
  const [brk, setBrk] = useState(false)
  const [ci, setCi] = useState<{ feel?: number; legs?: number; sick?: boolean } | null>(null)
  const view = v ?? data
  const run = async (fn: () => Promise<View | string>) => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await fn()
      if (typeof r === 'string') { setMsg(r); reload() } else setV(r)
      onChanged()
    } catch (e) { setMsg(`Error: ${(e as Error).message}`) } finally { setBusy(false) }
  }
  if (loading && !view) return <div className="card"><Skeleton h={56} w={56} style={{ borderRadius: '50%' }} /><Skeleton h={14} style={{ marginTop: 12 }} /><Skeleton h={14} w="60%" style={{ marginTop: 8 }} /></div>
  if (!view) return null
  const r = view.readiness
  const st = r.status
  const draft = ci ?? view.checkin ?? {}
  const asked = !!view.checkin && !ci
  const last = [...(rows.data?.rows ?? [])].reverse().find((x) => x.training_readiness || x.body_battery)
  const sendCheckin = (c: typeof draft) => run(() => api.post<View>('/api/readiness/checkin', c)).then(() => setCi(null))

  return (
    <div className="card">
      <div className="card-head"><span className="micro">Readiness</span><a className="small" href="#ajustes">{t('Measure HRV')}</a></div>
      <div className="row" style={{ gap: 14, flexWrap: 'nowrap' }}>
        <div className={`ring ready-${st}`} aria-label={r.score != null ? t('Score {n} out of 100', { n: r.score }) : undefined}>
          {r.score != null ? <b className="num" style={{ fontSize: 18 }}>{r.score}</b> : <Icon name={RICON[st]} size={24} />}
        </div>
        <div className="grow">
          <div style={{ fontWeight: 700, fontSize: 17 }} className={`ready-${st}`}>{RLABEL[st]}</div>
          {r.hrv_7d && <div className="small muted num">HRV 7 d {r.hrv_7d} ms · {t('normal')} {r.swc_low}–{r.swc_high}</div>}
        </div>
      </div>

      {!!r.components?.length && (
        <div className="rparts">
          {r.components.map((c) => (
            <div key={c.key} className="rpart">
              <span className="small">{c.label}</span>
              <div className="progress" aria-hidden><span style={{ width: `${c.score}%`, background: tone(c.score) }} /></div>
              <span className="small muted num">{c.value}</span>
            </div>
          ))}
        </div>
      )}
      {!!r.reasons.length && <ul className="small text-2" style={{ margin: '8px 0', paddingLeft: 18 }}>{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}

      {view.proposal && (
        <div className="proposal">
          <div className="small"><b>{t('Proposal for today:')}</b> “{view.proposal.from}” → <b>“{view.proposal.to}”</b> ({view.proposal.to_km} km)</div>
          {view.explanation
            ? <p className="small text-2" style={{ margin: '6px 0 0' }}><Icon name="sparkles" size={14} /> {view.explanation}</p>
            : <button className="btn btn-ghost btn-sm" style={{ paddingLeft: 0 }} disabled={busy} onClick={() => run(() => api.get<View>('/api/readiness?explain=true'))}><Icon name="sparkles" size={16} />{t('Why?')}</button>}
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => run(() => api.post<View>('/api/readiness/proposal', { accept: true }))}><Icon name="check" size={16} />{t('Ease off')}</button>
            <button className="btn btn-sm" disabled={busy} onClick={() => run(() => api.post<View>('/api/readiness/proposal', { accept: false }))}>{t('Keep the plan')}</button>
          </div>
        </div>
      )}
      {!view.proposal && view.workout?.status === 'modified' && view.workout.note && (
        <div style={{ marginTop: 10 }}><Banner tone="info">{t('Today')}: “{view.workout.title}”. {view.workout.note}</Banner></div>
      )}

      <hr />
      {asked ? (
        <div className="row small" style={{ justifyContent: 'space-between' }}>
          <span className="muted">{t('Today’s check-in:')} {draft.sick ? t('sick') : `${FEEL[(draft.feel ?? 3) - 1].toLowerCase()}, ${t('legs')} ${LEGS[(draft.legs ?? 3) - 1].toLowerCase()}`}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => setCi({ ...view.checkin })}>{t('Change')}</button>
        </div>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          <div className="small text-2">{t('How are you today? Two taps; it counts towards the score.')}</div>
          <Scale label={t('Overall feeling')} opts={FEEL} value={draft.feel} onPick={(x) => setCi({ ...draft, feel: x })} />
          <Scale label={t('Legs')} opts={LEGS} value={draft.legs} onPick={(x) => setCi({ ...draft, legs: x })} />
          <label className="row small" style={{ gap: 8 }}>
            <input type="checkbox" checked={!!draft.sick} onChange={(e) => setCi({ ...draft, sick: e.target.checked })} />{t('I’m ill (cold, fever…)')}
          </label>
          <div className="row">
            <button className="btn btn-sm btn-primary" disabled={busy || !(draft.feel || draft.legs || draft.sick)} onClick={() => sendCheckin(draft)}>{t('Save check-in')}</button>
            {ci && view.checkin && <button className="btn btn-sm btn-ghost" onClick={() => setCi(null)}>{t('Cancel')}</button>}
          </div>
        </div>
      )}

      {last && (
        <div className="mini-stats" style={{ marginTop: 12, gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
          <div><span className="micro">{t('Garmin readiness')}</span><b>{last.training_readiness ?? '–'}</b></div>
          <div><span className="micro">Body Battery</span><b>{last.body_battery ?? '–'}</b></div>
        </div>
      )}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn btn-sm btn-ghost" aria-expanded={more} onClick={() => setMore(!more)}>{t('Not feeling 100%?')}<Icon name="chevronDown" size={16} /></button>
      </div>
      {more && (
        <div style={{ marginTop: 6 }}>
          <p className="small muted">{t('Quality → easy and −30% volume for a few days, or active rest.')}</p>
          <div className="row">
            {[3, 5, 7].map((d) => (
              <button key={d} className="btn btn-sm" disabled={busy} onClick={() => run(async () => {
                const x = await api.post<unknown[]>('/api/not-feeling-100', { days: d, mode: 'reduce' })
                return t('{n} workouts adjusted over the next {d} days.', { n: x.length, d })
              })}>{t('Reduce {d} d', { d })}</button>
            ))}
            <button className="btn btn-sm" disabled={busy} onClick={() => run(async () => {
              const x = await api.post<unknown[]>('/api/not-feeling-100', { days: 3, mode: 'rest' })
              return t('{n} workouts changed to recovery runs.', { n: x.length })
            })}>{t('Rest 3 d')}</button>
            <button className="btn btn-sm" aria-expanded={brk} onClick={() => setBrk(!brk)}>{t('I’ve had a break')}</button>
          </div>
          {brk && <div style={{ marginTop: 10 }}><BreakForm onDone={(m) => { setMsg(m); setBrk(false); reload(); onChanged() }} /></div>}
        </div>
      )}
      {msg && <div style={{ marginTop: 10, whiteSpace: 'pre-wrap' }}><Banner tone={msg.startsWith('Error') ? 'bad' : 'info'}>{msg}</Banner></div>}
    </div>
  )
}
