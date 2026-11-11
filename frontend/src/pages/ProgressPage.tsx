import { useEffect, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, daysBetween, DIST_LABEL, fmtDate, garminActivityUrl, iso, useApi, VERDICT } from '../api'
import { Banner, Empty, Icon, Segmented, Skeleton, StatTile } from '../ui'
import { t } from '../i18n'

type Section = 'records' | 'pred' | 'load' | 'health'
type PR = { time_s: number; time: string; pace: string; date: string; approx: boolean; name?: string; external_id?: string; source?: string }
type Records = { records: Record<'all' | '1y' | '6m' | '1m', Record<string, PR>>; history_since: string | null; n_activities: number }
type Times = Record<string, { seconds: number; time: string; pace: string }>
type Pred = {
  models: Record<string, { label: string; source?: string; vdot?: number; times: Times }>
  consensus: Times; consensus_vdot: number | null; best_effort_vdot: number | null; current_vdot: number | null
  suggest_vdot: number | null; trend: { month: string; vdot: number }[]; window_days: number
}
type LoadPt = { date: string; load: number; ctl: number; atl: number; tsb: number; acwr: number | null }
type WRow = { date: string; hrv_rmssd?: number; rest_hr?: number; sleep_score?: number }

const PR_KEYS = ['1k', 'mile', '5k', '10k', 'half', 'marathon']
const PRED_KEYS = ['5k', '10k', 'half', 'marathon']
const MODEL_ORDER = ['vdot', 'riegel', 'garmin', 'hr']

function useTokens() {
  const read = () => {
    const cs = getComputedStyle(document.documentElement)
    const g = (n: string) => cs.getPropertyValue(n).trim()
    return { s1: g('--series-1'), s2: g('--series-2'), s3: g('--series-3'), muted: g('--muted'), border: g('--border'), good: g('--good') }
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
const tip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text)' } }

function RecordsView() {
  const { data, loading } = useApi<Records>('/api/records')
  const [win, setWin] = useState<'all' | '1y' | '6m' | '1m'>('all')
  if (loading && !data) return <Skeleton h={320} />
  if (!data) return null
  const rec = data.records[win]
  const today = iso(new Date())
  return (
    <div className="card">
      <div className="card-head" style={{ flexWrap: 'wrap' }}>
        <Segmented label={t('Period')} value={win} onChange={setWin} options={[['all', t('All time')], ['1y', t('12 months')], ['6m', t('6 months')], ['1m', t('30 days')]]} />
        {data.history_since && (
          <span className="small muted">
            {t('History since {date} · {n} activities', { date: fmtDate(data.history_since, { day: 'numeric', month: 'short', year: 'numeric' }), n: data.n_activities })} ·{' '}
            <a href="#ajustes" onClick={() => setTimeout(() => document.getElementById('importar')?.scrollIntoView({ behavior: 'smooth' }), 300)}>{t('Import earlier years')}</a>
          </span>
        )}
      </div>
      <div className="list">
        {PR_KEYS.map((k) => {
          const r = rec[k]
          const url = garminActivityUrl(r?.external_id)
          return (
            <div key={k} className="list-row">
              <div style={{ width: 92, fontWeight: 700 }}>{DIST_LABEL[k]}</div>
              {r ? (
                <>
                  <div className="grow">
                    <div className="big-time">{r.time}</div>
                    <div className="meta num">{r.pace} /km · {fmtDate(r.date, { day: 'numeric', month: 'short', year: 'numeric' })}{r.approx ? ` · ${t('approx.')}` : ''}</div>
                  </div>
                  <div className="right row" style={{ flexWrap: 'nowrap' }}>
                    {daysBetween(r.date, today) <= 30 && <span className="chip chip-accent">{t('NEW')}</span>}
                    {url && <a className="btn btn-ghost btn-icon" href={url} target="_blank" rel="noreferrer" aria-label={t('View the {dist} activity on Garmin', { dist: DIST_LABEL[k] })}><Icon name="external" size={18} /></a>}
                  </div>
                </>
              ) : <div className="grow muted">{t('No record')}</div>}
            </div>
          )
        })}
      </div>
      <p className="small muted" style={{ marginTop: 12, marginBottom: 0 }}>
        {t('Best efforts within any run (Garmin “fastest split”). “Approx.” = a whole activity of nearly the exact distance scaled at its pace, or an effort computed from GPS only (GPX files). If the watch has records older than the history, “All time” uses Garmin’s.')}
      </p>
    </div>
  )
}

function PredictionsView() {
  const { data, loading, reload } = useApi<Pred>('/api/predictions')
  const [msg, setMsg] = useState<string | null>(null)
  const c = useTokens()
  if (loading && !data) return <Skeleton h={320} />
  if (!data) return null
  const models = MODEL_ORDER.filter((m) => data.models[m])
  if (!models.length) return <div className="card"><Empty icon="trophy" title={t('No data to predict from')}>{t('Sync activities with efforts of at least a mile.')}</Empty></div>
  return (
    <div className="stack">
      {data.suggest_vdot && (
        <Banner tone="info">
          {t('Your recent efforts point to VDOT')} <b>{data.suggest_vdot}</b> {t('and your plan uses')} <b>{data.current_vdot}</b>.{' '}
          <button className="btn btn-sm" style={{ marginLeft: 8 }} onClick={async () => {
            const r = await api.post<{ vdot: number; workouts_updated: number; garmin_updated: number }>('/api/athlete/recalibrate', { vdot: data.suggest_vdot, source: t('best efforts 90 d') })
            setMsg(t('VDOT {vdot}: {n} workouts re-paced, {g} updated on Garmin.', { vdot: r.vdot, n: r.workouts_updated, g: r.garmin_updated }))
            reload()
          }}>{t('Recalibrate paces')}</button>
        </Banner>
      )}
      {msg && <Banner tone="ok">{msg}</Banner>}
      <div className="card">
        <div className="card-head"><span className="micro">{t('Race prediction')}</span>{data.consensus_vdot && <span className="chip num">{t('Consensus VDOT')} {data.consensus_vdot}</span>}</div>
        <div className="only-mobile list">
          {PRED_KEYS.map((k) => (
            <div key={k} className="list-row" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 4 }}>
              <div className="row spread">
                <b>{DIST_LABEL[k]}</b>
                <span><b className="big-time">{data.consensus[k]?.time ?? '–'}</b> <span className="small muted">{data.consensus[k]?.pace}/km</span></span>
              </div>
              <div className="small muted num">{models.map((m) => `${data.models[m].label} ${data.models[m].times[k]?.time ?? '–'}`).join(' · ')}</div>
            </div>
          ))}
        </div>
        <div className="table-wrap only-desktop">
          <table>
            <thead><tr><th>{t('Distance')}</th><th className="n">{t('Consensus')}</th>{models.map((m) => <th key={m} className="n">{data.models[m].label}</th>)}</tr></thead>
            <tbody>
              {PRED_KEYS.map((k) => (
                <tr key={k}>
                  <td style={{ fontWeight: 600 }}>{DIST_LABEL[k]}</td>
                  <td className="n"><b className="big-time" style={{ fontSize: 17 }}>{data.consensus[k]?.time ?? '–'}</b><div className="small muted">{data.consensus[k]?.pace}/km</div></td>
                  {models.map((m) => <td key={m} className="n num">{data.models[m].times[k]?.time ?? '–'}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="small muted" style={{ margin: '12px 0 0', paddingLeft: 18 }}>
          {models.map((m) => <li key={m}><b>{data.models[m].label}</b>{data.models[m].vdot ? ` (VDOT ${data.models[m].vdot})` : ''}: {data.models[m].source}</li>)}
          <li>{t('Consensus = median of the models. VDOT and Riegel use your best efforts of the last {n} days; for long distances they assume enough volume.', { n: data.window_days })}</li>
        </ul>
      </div>
      <PaceInsightsCard onApplied={reload} />
      {data.trend.length > 1 && (
        <div className="card">
          <div className="card-head"><span className="micro">{t('Fitness trend (VDOT by month)')}</span></div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={data.trend} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid stroke={c.border} vertical={false} />
              <XAxis dataKey="month" stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} domain={['dataMin - 1', 'dataMax + 1']} />
              <Tooltip {...tip} />
              <Line dataKey="vdot" name="VDOT" stroke={c.s1} strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

function LoadView() {
  const { data, loading } = useApi<{ series: LoadPt[] }>('/api/load?days=120')
  const est = useApi<{ vdot: number; n_runs: number } | null>('/api/fitness-estimate')
  const c = useTokens()
  if (loading && !data) return <Skeleton h={320} />
  const all = data?.series ?? []
  const first = all.findIndex((p) => p.load > 0)
  const series = first >= 0 ? all.slice(Math.max(0, first - 3)) : []
  const last = series[series.length - 1]
  const acwr = last?.acwr
  return (
    <div className="stack">
      {last && (
        <Banner tone={acwr && acwr > 1.5 ? 'bad' : acwr && acwr > 1.3 ? 'warn' : last.tsb < -20 ? 'warn' : 'info'}>
          {acwr && acwr > 1.3 ? t('You have trained much more than usual this week. Watch for injury signs and keep the easy days easy.')
            : last.tsb < -20 ? t('You are carrying quite a bit of fatigue. Normal in a hard block; make sure recovery weeks are respected.')
              : last.tsb > 5 ? t('You are fresh: good for a race or a test. If it lasts weeks, you are losing fitness.')
                : t('Load under control: you are building fitness without excess fatigue.')}
        </Banner>
      )}
      <div className="grid stats">
        <StatTile label={t('Fitness')} value={last ? Math.round(last.ctl) : '–'} sub={t('Training of the last 6 weeks. Higher = fitter.')} />
        <StatTile label={t('Fatigue')} value={last ? Math.round(last.atl) : '–'} sub={t('Training of the last 7 days.')} />
        <StatTile label={t('Freshness')} value={last ? Math.round(last.tsb) : '–'} sub={t('Fitness − fatigue. Between −10 and +5 is ideal.')} />
        <StatTile label={t('Load vs usual')} value={acwr ?? '–'} tone={acwr && acwr > 1.5 ? 'bad' : acwr && acwr > 1.3 ? 'warn' : ''} sub={t('Last week ÷ last 4 weeks. Safe: 0.8–1.3.')} />
        <StatTile label={t('Level from your HR')} value={est.data?.vdot ?? '–'} sub={est.data ? t('VDOT estimated from {n} runs (rough guide)', { n: est.data.n_runs }) : t('Needs max/resting HR')} />
      </div>
      <div className="card">
        <div className="card-head"><span className="micro">{t('Fitness, fatigue and freshness')}</span></div>
        {series.length === 0 ? <Empty icon="activity" title={t('No load yet')}>{t('Sync Garmin.')}</Empty> : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={series} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid stroke={c.border} vertical={false} />
              <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} minTickGap={30} />
              <YAxis stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} />
              <ReferenceArea y1={-10} y2={5} fill={c.good} fillOpacity={0.08} />
              <Tooltip {...tip} />
              <Legend />
              <Line dataKey="ctl" name={t('Fitness')} stroke={c.s2} strokeWidth={2} dot={false} />
              <Line dataKey="atl" name={t('Fatigue')} stroke={c.s1} strokeWidth={2} dot={false} />
              <Line dataKey="tsb" name={t('Freshness')} stroke={c.s3} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

function HealthView() {
  const { data, loading } = useApi<{ rows: WRow[]; readiness: { swc_low: number | null; swc_high: number | null } }>('/api/wellness?days=60')
  const c = useTokens()
  if (loading && !data) return <Skeleton h={320} />
  const rows = data?.rows ?? []
  return (
    <div className="stack">
      <div className="card">
        <div className="card-head"><span className="micro">{t('Overnight HRV (RMSSD)')}</span></div>
        <p className="small muted">{t('Band = your normal range (60-day baseline ± 0.5 SD). Several days below it → lower the intensity.')}</p>
        {!rows.some((r) => r.hrv_rmssd) ? <Empty icon="heart" title={t('No HRV yet')}>{t('Garmin, Zepp or a measurement with a chest/arm strap.')}</Empty> : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={rows} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid stroke={c.border} vertical={false} />
              <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} minTickGap={30} />
              <YAxis stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} domain={['auto', 'auto']} unit=" ms" width={64} />
              <Tooltip {...tip} />
              {data?.readiness.swc_low && data.readiness.swc_high && <ReferenceArea y1={data.readiness.swc_low} y2={data.readiness.swc_high} fill={c.good} fillOpacity={0.14} />}
              <Line dataKey="hrv_rmssd" name="HRV" stroke={c.s2} strokeWidth={2} dot={{ r: 3 }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      <div className="card">
        <div className="card-head"><span className="micro">{t('Sleep and resting HR')}</span></div>
        {!rows.some((r) => r.sleep_score || r.rest_hr) ? <Empty icon="moon" title={t('No data')} /> : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={rows} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid stroke={c.border} vertical={false} />
              <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} minTickGap={30} />
              <YAxis stroke={c.muted} fontSize={12} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
              <Tooltip {...tip} />
              <Legend />
              <Line dataKey="sleep_score" name={t('Sleep (0–100)')} stroke={c.s2} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              <Line dataKey="rest_hr" name={t('Resting HR (bpm)')} stroke={c.s1} strokeWidth={2} dot={{ r: 3 }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

type Insights = { pending: { from: number; to: number; reason: string } | null; log: { date: string; from: number; to: number; reason: string }[]
  sessions: { date: string; verdict: string }[]; auto: boolean }

function PaceInsightsCard({ onApplied }: { onApplied: () => void }) {
  const { data, reload } = useApi<Insights>('/api/pace-insights')
  const [busy, setBusy] = useState(false)
  if (!data) return null
  return (
    <div className="card">
      <div className="card-head"><span className="micro">{t('Automatic paces (post-run analysis)')}</span><span className={`chip ${data.auto ? 'chip-good' : ''}`}>{data.auto ? t('Automatic') : t('Manual')}</span></div>
      <p className="small text-2">{t('Each quality session is compared lap by lap with the plan. If 2 of the last 3 (21 days) are easier — or harder — than planned, VDOT goes up — or down — by 0.5 and the workouts and the watch are updated. At most one change a week, and never in the 10 days before your goal race.')}</p>
      {data.sessions.length > 0 ? (
        <div className="row" style={{ marginBottom: 10 }}>
          {data.sessions.map((x) => <span key={x.date} className={`chip ${VERDICT[x.verdict]?.[1] ?? ''}`}>{fmtDate(x.date, { day: 'numeric', month: 'short' })} · {VERDICT[x.verdict]?.[0] ?? x.verdict}</span>)}
        </div>
      ) : <p className="small muted">{t('No OpenRun quality sessions analysed yet. They start with your plan.')}</p>}
      {data.pending && (
        <Banner tone="info">
          {t('Proposal')}: VDOT {data.pending.from} → <b>{data.pending.to}</b> ({data.pending.reason}).{' '}
          <button className="btn btn-sm" disabled={busy} style={{ marginLeft: 6 }} onClick={async () => {
            setBusy(true)
            try { await api.post('/api/pace-insights/apply'); reload(); onApplied() } finally { setBusy(false) }
          }}>{t('Apply')}</button>
        </Banner>
      )}
      {data.log.length > 0 && (
        <ul className="small text-2" style={{ margin: '8px 0 0', paddingLeft: 18 }}>
          {data.log.slice().reverse().map((x) => <li key={x.date + x.to}>{fmtDate(x.date, { day: 'numeric', month: 'short' })}: VDOT {x.from} → {x.to} · {x.reason}</li>)}
        </ul>
      )}
    </div>
  )
}

export default function ProgressPage() {
  const [sec, setSec] = useState<Section>(() => {
    try { const v = localStorage.getItem('progress-sec') as Section; return ['records', 'pred', 'load', 'health'].includes(v) ? v : 'records' } catch { return 'records' }
  })
  useEffect(() => { try { localStorage.setItem('progress-sec', sec) } catch { /* private mode */ } }, [sec])
  return (
    <div className="stack">
      <Segmented label={t('Section')} value={sec} onChange={setSec}
        options={[['records', t('Records')], ['pred', t('Predictions')], ['load', t('Load')], ['health', t('Health')]]} />
      {sec === 'records' && <RecordsView />}
      {sec === 'pred' && <PredictionsView />}
      {sec === 'load' && <LoadView />}
      {sec === 'health' && <HealthView />}
    </div>
  )
}
