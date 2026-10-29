import { useEffect, useRef, useState } from 'react'
import { api, fmtDate, useApi } from '../api'
import type { Me } from '../App'
import { DONATE_URL, REPO_URL } from '../project'
import { Banner, Icon, Segmented, type IconName } from '../ui'
import { getLang, LANGS, locale, setLang, t, type Lang } from '../i18n'

type Athlete = { name: string; sex: string; age: number | null; max_hr: number | null; rest_hr: number | null; lthr: number | null; vdot: number | null; vdot_source: string | null; hr_zones?: { zone: number; low: number; high: number }[] }
type GStatus = { connected: boolean; name?: string; needs_mfa?: boolean; error?: string; last_sync?: string | null }
type CoachInfo = { provider: string; model: string; configured: boolean
  mcp: { remote: false; command: string; args: string[]; cwd: string } | { remote: true; url: string; image: string } }

// Personal API token for the MCP server: each user's Claude Desktop sees only their own data.
function McpToken({ onToken }: { onToken: (t: string | null) => void }) {
  const acc = useApi<{ has_token?: boolean }>('/api/account')
  const [tok, setTok] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const gen = async () => {
    if (acc.data?.has_token && !confirm(t('A new token will be generated and the old one will stop working. Continue?'))) return
    setBusy(true)
    try { const r = await api.post<{ token: string }>('/api/account/token'); setTok(r.token); onToken(r.token); acc.reload() } finally { setBusy(false) }
  }
  return (
    <div className="stack" style={{ gap: 8, margin: '10px 0' }}>
      {tok
        ? <Banner tone="ok">{t('Your personal token (copy it now: it won\'t be shown again). It is already in the configuration below.')}</Banner>
        : <div className="small text-2">{acc.data?.has_token ? t('You already have a personal token. If you lost it, generate a new one.') : t('First generate your personal token: it only gives access to your data.')}</div>}
      <div className="row">
        <button className="btn btn-sm btn-primary" disabled={busy} onClick={gen}>{acc.data?.has_token ? t('Generate new token') : t('Generate token')}</button>
        {acc.data?.has_token && <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => api.del('/api/account/token').then(() => { setTok(null); onToken(null); acc.reload() })}>{t('Revoke')}</button>}
      </div>
    </div>
  )
}

function ConnHead({ icon, title, status, tone = 'good' }: { icon: IconName; title: string; status: string | null; tone?: 'good' | 'warn' }) {
  return (
    <div className="row" style={{ flexWrap: 'nowrap' }}>
      <div style={{ width: 48, height: 48, borderRadius: 12, background: 'var(--surface-2)', display: 'grid', placeItems: 'center', flex: 'none' }}><Icon name={icon} size={24} /></div>
      <h3 className="grow">{title}</h3>
      {status && <span className={`chip chip-${tone}`}>{status}</span>}
    </div>
  )
}

export function GarminCard({ onChange }: { onChange: () => void }) {
  const [st, setSt] = useState<GStatus | null>(null)
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [code, setCode] = useState('')
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad' | 'info'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => api.get<GStatus>('/api/garmin/status').then(setSt).catch(() => {})
  useEffect(() => { load() }, [])

  const go = async (fn: () => Promise<GStatus>) => {
    setBusy(true)
    setMsg(null)
    try { setSt(await fn()); onChange() } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) } finally { setBusy(false) }
  }

  return (
    <div className="card">
      <ConnHead icon="watch" title="Garmin Connect" status={st ? (st.connected ? t('Connected') : t('Disconnected')) : null} tone={st?.connected ? 'good' : 'warn'} />
      <div style={{ marginTop: 12 }}>
        {st?.connected ? (
          <>
            <p className="small text-2">{t('Connected')}{st.name ? ` ${t('as {name}', { name: st.name })}` : ''}. {t('Last sync')}: {st.last_sync ? new Date(st.last_sync).toLocaleString(locale()) : t('never')}.</p>
            <div className="row">
              <button className="btn" disabled={busy} onClick={async () => {
                setBusy(true)
                setMsg({ tone: 'info', text: t('Downloading the whole history…') })
                try {
                  const r = await api.post<{ activities: number }>('/api/garmin/sync?days=14&full=true')
                  setMsg({ tone: 'ok', text: t('{n} activities synced (full history).', { n: r.activities }) })
                  load(); onChange()
                } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) } finally { setBusy(false) }
              }}><Icon name="refresh" />{t('Sync full history')}</button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => go(async () => { await api.post('/api/garmin/logout'); return { connected: false } })}>{t('Disconnect')}</button>
            </div>
          </>
        ) : st?.needs_mfa ? (
          <form className="row" style={{ alignItems: 'flex-end' }} onSubmit={(e) => { e.preventDefault(); go(() => api.post('/api/garmin/mfa', { code })) }}>
            <label className="field" style={{ maxWidth: 200 }}>{t('Verification code')}
              <input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
            </label>
            <button className="btn btn-primary" disabled={busy}>{t('Verify')}</button>
          </form>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); go(() => api.post('/api/garmin/login', { email, password: pw })) }}>
            <p className="small muted">{t('Your password is not stored: only the session tokens, in the server\'s data folder. Unofficial Garmin API.')}</p>
            <div className="form-grid">
              <label className="field">{t('Garmin Connect email')}
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
              </label>
              <label className="field">{t('Password')}
                <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" />
              </label>
            </div>
            <button className="btn btn-primary" style={{ marginTop: 12 }} disabled={busy}>{busy ? t('Connecting…') : t('Connect')}</button>
          </form>
        )}
      </div>
      {msg && <div style={{ marginTop: 10 }}><Banner tone={msg.tone}>{msg.text}</Banner></div>}
    </div>
  )
}

// --- Helio Strap via Web Bluetooth (standard Heart Rate Service 0x180D, with RR intervals)
function parseHrm(dv: DataView) {
  const flags = dv.getUint8(0)
  let i = 1
  const hr = flags & 0x1 ? dv.getUint16(i, true) : dv.getUint8(i)
  i += flags & 0x1 ? 2 : 1
  if (flags & 0x8) i += 2 // energy expended
  const rr: number[] = []
  if (flags & 0x10) for (; i + 1 < dv.byteLength; i += 2) rr.push((dv.getUint16(i, true) / 1024) * 1000)
  return { hr, rr }
}

function HelioCard() {
  const [hr, setHr] = useState<number | null>(null)
  const [state, setState] = useState<'idle' | 'connected' | 'measuring'>('idle')
  const [left, setLeft] = useState(0)
  const [res, setRes] = useState<string | null>(null)
  const [hasRR, setHasRR] = useState(false)
  const rr = useRef<number[]>([])
  const hrs = useRef<number[]>([])
  const measuring = useRef(false)
  const devRef = useRef<{ gatt?: { disconnect: () => void } } | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const bt = (navigator as any).bluetooth

  const connect = async () => {
    setRes(null)
    try {
      const dev = await bt.requestDevice({ filters: [{ services: ['heart_rate'] }] })
      devRef.current = dev
      const server = await dev.gatt.connect()
      const svc = await server.getPrimaryService('heart_rate')
      const ch = await svc.getCharacteristic('heart_rate_measurement')
      await ch.startNotifications()
      ch.addEventListener('characteristicvaluechanged', (ev: Event) => {
        const v = parseHrm((ev.target as unknown as { value: DataView }).value)
        setHr(v.hr)
        if (v.rr.length) setHasRR(true)
        if (measuring.current) {
          rr.current.push(...v.rr)
          hrs.current.push(v.hr)
        }
      })
      dev.addEventListener('gattserverdisconnected', () => { setState('idle'); setHr(null) })
      setState('connected')
    } catch (e) {
      setRes(`Error: ${(e as Error).message}`)
    }
  }

  const measure = () => {
    rr.current = []
    hrs.current = []
    measuring.current = true
    setState('measuring')
    let s = 180
    setLeft(s)
    const timer = setInterval(async () => {
      s -= 1
      setLeft(s)
      if (s > 0) return
      clearInterval(timer)
      measuring.current = false
      setState('connected')
      // Discard first 30 s (stabilisation), as in standard short-term HRV protocols (Task Force 1996; Plews 2013)
      let acc = 0
      const kept = rr.current.filter((x) => (acc += x) > 30000)
      const avg = hrs.current.length ? hrs.current.reduce((a, b) => a + b, 0) / hrs.current.length : undefined
      try {
        const r = await api.post<{ rmssd: number; ln_rmssd: number; readiness: { status: string } }>('/api/wellness/hrv-reading', { rr_ms: kept, avg_hr: avg })
        setRes(`RMSSD ${r.rmssd} ms (lnRMSSD ${r.ln_rmssd}) · readiness: ${r.readiness.status}`)
      } catch (e) {
        setRes(`Error: ${(e as Error).message}`)
      }
    }, 1000)
  }

  return (
    <div className="card">
      <ConnHead icon="heart" title={t('Heart-rate strap (HRV)')} status={state === 'idle' ? null : t('Connected')} />
      <details style={{ marginTop: 10 }}>
        <summary className="small">{t('How to use it (e.g. Amazfit Helio Strap)')}</summary>
        <p className="small text-2" style={{ marginTop: 6 }}>
        <strong>{t('While running:')}</strong> {t('turn on heart-rate broadcast on the strap (Zepp app for the Helio Strap) and pair it with your watch as an HR sensor. The watch records the strap’s heart rate and it arrives here with the sync.')}<br />
        <strong>{t('Morning HRV:')}</strong> {t('after waking up, lying down, connect here and measure for 3 min (Chrome/Edge, Web Bluetooth).')}
        </p>
      </details>
      {!bt ? <div style={{ marginTop: 12 }}><Banner>{t('This browser doesn\'t support Web Bluetooth. Use Chrome or Edge.')}</Banner></div> : (
        <div className="row" style={{ marginTop: 12 }}>
          {state === 'idle' && <button className="btn btn-primary" onClick={connect}><Icon name="bluetooth" />{t('Connect strap')}</button>}
          {state !== 'idle' && <span className="stat-value" style={{ margin: 0 }}>{hr ?? '–'}<small>{t('bpm')}</small></span>}
          {state === 'connected' && <button className="btn btn-primary" onClick={measure} disabled={!hasRR}>{hasRR ? t('Measure HRV (3 min)') : t('Waiting for RR intervals…')}</button>}
          {state === 'measuring' && (
            <div className="grow" style={{ maxWidth: 260 }}>
              <div className="small">{t('Stay still and breathe normally… {n} s', { n: left })}</div>
              <div className="progress" style={{ marginTop: 6 }}><span style={{ width: `${((180 - left) / 180) * 100}%` }} /></div>
            </div>
          )}
          {state !== 'idle' && <button className="btn btn-ghost" onClick={() => devRef.current?.gatt?.disconnect()}>{t('Disconnect')}</button>}
        </div>
      )}
      {res && <div style={{ marginTop: 10 }}><Banner tone={res.startsWith('Error') ? 'bad' : 'ok'}>{res}</Banner></div>}
    </div>
  )
}

function ImportCard() {
  const [res, setRes] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const upload = async (f: File) => {
    const fd = new FormData()
    fd.append('file', f)
    try {
      const r = await api.post<{ imported_days: number }>('/api/wellness/import', fd)
      setRes({ tone: 'ok', text: t('{n} days imported.', { n: r.imported_days }) })
    } catch (e) {
      setRes({ tone: 'bad', text: (e as Error).message })
    }
  }
  return (
    <div className="card">
      <ConnHead icon="heart" title={t('Import Zepp data (HRV, sleep)')} status={null} />
      <p className="small text-2" style={{ marginTop: 10 }}>{t('In the Zepp app: Profile › Settings › Account › Export data. Upload the .zip or a CSV with date + HRV / resting HR / sleep.')}</p>
      <label className="field" style={{ maxWidth: 360 }}>{t('File')}
        <input type="file" accept=".zip,.csv" style={{ paddingTop: 9 }} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </label>
      {res && <div style={{ marginTop: 10 }}><Banner tone={res.tone}>{res.text}</Banner></div>}
    </div>
  )
}

type ImportJob = { id: string; state: 'running' | 'done' | 'error'; file: number; files: number; done: number; total: number; error: string | null
  stats: { imported?: number; duplicates?: number; with_efforts?: number; oldest?: string | null; newest?: string | null } }

export function HistoryImportCard() {
  const [job, setJob] = useState<ImportJob | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const timer = useRef<number | null>(null)
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current) }, [])

  const upload = async (list: FileList) => {
    setErr(null)
    setJob(null)
    setUploading(true)
    const fd = new FormData()
    Array.from(list).forEach((f) => fd.append('files', f))
    try {
      const { job: id } = await api.post<{ job: string }>('/api/import/history', fd)
      setUploading(false)
      timer.current = window.setInterval(async () => {
        try {
          const j = await api.get<ImportJob>(`/api/import/history/${id}`)
          setJob(j)
          if (j.state !== 'running' && timer.current) window.clearInterval(timer.current)
        } catch (e) {
          if (timer.current) window.clearInterval(timer.current)
          setErr((e as Error).message)
        }
      }, 700)
    } catch (e) {
      setUploading(false)
      setErr((e as Error).message)
    }
  }
  const pct = job && job.total ? Math.round((job.done / job.total) * 100) : 0
  const st = job?.stats ?? {}
  return (
    <div className="card" id="importar">
      <ConnHead icon="upload" title={t('Import history (Strava, FIT, GPX, TCX)')} status={null} />
      <p className="small text-2" style={{ marginTop: 10 }}>
        {t('Bring in runs from earlier years for complete records and trends. Best efforts (1K, mile, 5K, 10K, half, marathon) are computed for each activity, and runs already present are skipped.')}
      </p>
      <details style={{ marginBottom: 10 }}>
        <summary className="small">{t('How to get your files')}</summary>
        <ul className="small text-2" style={{ margin: '6px 0 0', paddingLeft: 18 }}>
          <li><b>Strava:</b> {t('strava.com › Settings › My Account › “Download or Delete Your Account” › Request Archive. You get an email with a .zip: upload it as is (it can be several GB; it takes a few minutes).')}</li>
          <li><b>{t('Garmin (full export):')}</b> {t('Garmin Account › Privacy › Export your data. Upload the .zip.')}</li>
          <li><b>{t('Single files:')}</b> {t('.fit, .gpx or .tcx files (also .gz) from any watch or app.')}</li>
        </ul>
      </details>
      <label className="field" style={{ maxWidth: 420 }}>{t('Files')}
        <input type="file" multiple accept=".zip,.fit,.gpx,.tcx,.gz" style={{ paddingTop: 9 }} disabled={uploading || job?.state === 'running'}
          onChange={(e) => e.target.files?.length && upload(e.target.files)} />
      </label>
      {uploading && <div style={{ marginTop: 10 }}><Banner tone="info">{t('Uploading…')}</Banner></div>}
      {job?.state === 'running' && (
        <div style={{ marginTop: 12 }} aria-live="polite">
          <div className="small">{t('Processing')}{job.files > 1 ? ` ${t('file {n}/{total}', { n: job.file, total: job.files })}` : ''}: {job.done}/{job.total || '…'} · {t('{n} runs imported', { n: st.imported ?? 0 })}</div>
          <div className="progress" style={{ marginTop: 6 }}><span style={{ width: `${pct}%` }} /></div>
        </div>
      )}
      {job?.state === 'done' && (
        <div style={{ marginTop: 12 }}>
          <Banner tone="ok">
            {t('{n} runs imported', { n: st.imported ?? 0 })}{st.oldest ? ` (${fmtDate(st.oldest, { month: 'short', year: 'numeric' })} – ${fmtDate(st.newest ?? st.oldest, { month: 'short', year: 'numeric' })})` : ''}, {t('{n} with efforts for records, {d} already present.', { n: st.with_efforts ?? 0, d: st.duplicates ?? 0 })}{' '}
            <a href="#progreso">{t('View records')}</a>
          </Banner>
        </div>
      )}
      {(err || job?.state === 'error') && <div style={{ marginTop: 10 }}><Banner tone="bad">{err ?? job?.error}</Banner></div>}
    </div>
  )
}

const ZONE_COLORS = ['var(--z1)', 'var(--z2)', 'var(--z3)', 'var(--z4)', 'var(--z5)']

function ProfileCard() {
  const [a, setA] = useState<Athlete | null>(null)
  const [race, setRace] = useState({ distance: '5k', time: '' })
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  useEffect(() => { api.get<Athlete>('/api/athlete').then(setA).catch(() => {}) }, [])
  if (!a) return null
  const num = (v: string) => (v === '' ? null : +v)
  return (
    <div className="card">
      <ConnHead icon="user" title={t('Profile and zones')} status={a.vdot ? `VDOT ${a.vdot}` : null} />
      <div className="form-grid" style={{ marginTop: 14 }}>
        <label className="field">{t('Sex')}<select value={a.sex} onChange={(e) => setA({ ...a, sex: e.target.value })}><option value="male">{t('Male')}</option><option value="female">{t('Female')}</option></select></label>
        <label className="field">{t('Age')}<input type="number" inputMode="numeric" value={a.age ?? ''} onChange={(e) => setA({ ...a, age: num(e.target.value) })} /></label>
        <label className="field">{t('Max HR')}<input type="number" inputMode="numeric" value={a.max_hr ?? ''} onChange={(e) => setA({ ...a, max_hr: num(e.target.value) })} /></label>
        <label className="field">{t('Resting HR')}<input type="number" inputMode="numeric" value={a.rest_hr ?? ''} onChange={(e) => setA({ ...a, rest_hr: num(e.target.value) })} /></label>
        <label className="field">{t('Threshold HR (LTHR)')}<input type="number" inputMode="numeric" value={a.lthr ?? ''} onChange={(e) => setA({ ...a, lthr: num(e.target.value) })} /></label>
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn btn-primary" onClick={() => api.put<Athlete>('/api/athlete', a).then((r) => { setA(r); setMsg({ tone: 'ok', text: t('Saved') }) })}>{t('Save')}</button>
        {a.vdot_source && <span className="small muted">VDOT {a.vdot} · {t('source')}: {a.vdot_source}</span>}
      </div>
      {a.hr_zones && (
        <div style={{ marginTop: 14 }}>
          <div className="micro" style={{ marginBottom: 6 }}>{t('HR zones')}</div>
          <div style={{ display: 'flex', gap: 2, borderRadius: 8, overflow: 'hidden' }}>
            {a.hr_zones.map((z, i) => (
              <div key={z.zone} style={{ flex: 1, background: ZONE_COLORS[i], color: i === 4 ? '#fff' : '#0E1116', padding: '6px 4px', textAlign: 'center', fontSize: 12, fontWeight: 600 }}>
                Z{z.zone}<br /><span className="num">{z.low}–{z.high}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <hr />
      <h3>{t('New race result or test')}</h3>
      <p className="small muted">{t('Recalculates your VDOT and the paces of all future workouts (including those already on the watch).')}</p>
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="field" style={{ width: 140 }}>{t('Distance')}
          <select value={race.distance} onChange={(e) => setRace({ ...race, distance: e.target.value })}>
            {[['mile', t('Mile')], ['3k', '3K'], ['5k', '5K'], ['10k', '10K'], ['15k', '15K'], ['half', t('Half')], ['marathon', t('Marathon')]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="field" style={{ width: 160 }}>{t('Time')}<input placeholder={t('mm:ss or h:mm:ss')} value={race.time} onChange={(e) => setRace({ ...race, time: e.target.value })} /></label>
        <button className="btn" disabled={!race.time} onClick={() => api.post<{ vdot: number; workouts_updated: number; garmin_updated?: number }>('/api/athlete/race-result', { ...race, recalibrate: true })
          .then((r) => { setMsg({ tone: 'ok', text: `VDOT ${r.vdot} · ${t('{n} workouts re-paced', { n: r.workouts_updated })}${r.garmin_updated ? ` · ${t('{n} updated on Garmin', { n: r.garmin_updated })}` : ''}` }); setA({ ...a, vdot: r.vdot }) })
          .catch((e) => setMsg({ tone: 'bad', text: e.message }))}>{t('Apply')}</button>
      </div>
      {msg && <div style={{ marginTop: 10 }}><Banner tone={msg.tone}>{msg.text}</Banner></div>}
    </div>
  )
}

function CopyBlock({ text }: { text: string }) {
  const [ok, setOk] = useState(false)
  return (
    <div style={{ position: 'relative' }}>
      <pre style={{ background: 'var(--surface-2)', borderRadius: 10, padding: 12, fontSize: 12, overflowX: 'auto', margin: '8px 0' }}>{text}</pre>
      <button className="btn btn-sm" style={{ position: 'absolute', top: 6, right: 6 }} onClick={() => navigator.clipboard?.writeText(text).then(() => { setOk(true); setTimeout(() => setOk(false), 1500) })}>
        {ok ? t('Copied') : t('Copy')}
      </button>
    </div>
  )
}

function CoachCard() {
  const { data } = useApi<CoachInfo>('/api/coach/info')
  const [tab, setTab] = useState<'mcp' | 'nvidia' | 'gemini' | 'ollama' | 'api' | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [how, setHow] = useState<'docker' | 'clone'>('docker')
  if (!data) return null
  const shown = tab ?? (['nvidia', 'gemini', 'ollama'].includes(data.provider) ? data.provider as 'nvidia' | 'gemini' | 'ollama' : data.provider === 'anthropic' ? 'api' : 'nvidia')
  const tk = token ?? t('<your personal token>')
  const server = !data.mcp.remote
    ? { command: data.mcp.command, args: data.mcp.args, env: { PYTHONPATH: data.mcp.cwd } }
    : how === 'docker'
      ? { command: 'docker', args: ['run', '-i', '--rm', '-e', 'OPENRUN_URL', '-e', 'OPENRUN_API_TOKEN', data.mcp.image, 'python', '-m', 'app.mcp_server'],
          env: { OPENRUN_URL: data.mcp.url, OPENRUN_API_TOKEN: tk } }
      : { command: `${t('<path to repo>')}/backend/.venv/bin/python`, args: ['-m', 'app.mcp_server'],
          env: { PYTHONPATH: `${t('<path to repo>')}/backend`, OPENRUN_URL: data.mcp.url, OPENRUN_API_TOKEN: tk } }
  const claudeCfg = JSON.stringify({ mcpServers: { openrun: server } }, null, 2)
  return (
    <div className="card">
      <ConnHead icon="sparkles" title={t('AI coach')} status={`${data.provider} · ${data.configured ? t('ready') : t('not configured')}`} tone={data.configured ? 'good' : 'warn'} />
      <p className="small text-2" style={{ marginTop: 10 }}>{t('The coach runs inside OpenRun with the provider configured on the server. The tools and rules are the same in every case.')}</p>
      <Segmented label={t('Coach option')} value={shown} onChange={setTab}
        options={[['nvidia', t('Free NVIDIA')], ['gemini', t('Free Gemini')], ['api', t('Paid API')], ['ollama', t('Local Ollama')], ['mcp', t('Outside the app (MCP)')]]} />
      <div style={{ marginTop: 12 }} className="small">
        {shown === 'mcp' && (
          <>
            <p><b>{t('No extra cost with Claude (Free/Pro/Max):')}</b> {t('connect OpenRun as an MCP server in Claude Desktop and chat there; Claude uses your data and creates workouts that show up here. Claude Desktop settings › Developer › Edit config and add:')}</p>
            {data.mcp.remote && (
              <>
                <p className="muted">{t('OpenRun runs on a server: the MCP server runs on your computer and talks to it with your personal token.')}</p>
                <McpToken onToken={setToken} />
                <Segmented label={t('How to run the MCP server')} value={how} onChange={setHow} options={[['docker', t('With Docker (nothing else to install)')], ['clone', t('From a clone of the repo')]]} />
                <div style={{ height: 10 }} />
              </>
            )}
            <CopyBlock text={claudeCfg} />
            <p className="muted">{t('Restart Claude Desktop. It also works with Gemini CLI (free with a Google account) in ~/.gemini/settings.json with the same mcpServers block. ChatGPT/Claude/Gemini subscriptions don’t include API access for your own apps: that’s why MCP is used.')}</p>
          </>
        )}
        {shown === 'nvidia' && (
          <>
            <p><b>{t('Free in-app chat with NVIDIA:')}</b> {t('create an account at build.nvidia.com (NVIDIA Developer, phone verification, no card), generate an API key (nvapi-…) and set:')}</p>
            <CopyBlock text={'OPENRUN_PROVIDER=nvidia\nNVIDIA_API_KEY=nvapi-...\n# optional: OPENRUN_MODEL=minimaxai/minimax-m3.1-flash (default)'} />
            <p className="muted">{t('~40 requests per minute (each coach answer can use several). Trial/evaluation terms: NVIDIA may limit or end access. On a server, set them as environment variables (.env).')}</p>
          </>
        )}
        {shown === 'gemini' && (
          <>
            <p><b>{t('Free in-app chat:')}</b> {t('create an API key in Google AI Studio (free tier with daily limits) and start with:')}</p>
            <CopyBlock text={'export OPENRUN_PROVIDER=gemini\nexport GEMINI_API_KEY=...\n./run.sh'} />
            <p className="muted">{t('Note: on the free tier Google may use the conversations to improve its products (this is health data).')}</p>
          </>
        )}
        {shown === 'ollama' && (
          <>
            <p><b>{t('100% local and free:')}</b> {t('install Ollama and a model with tool support (e.g. qwen3:8b, ~5 GB):')}</p>
            <CopyBlock text={'ollama pull qwen3:8b\nexport OPENRUN_PROVIDER=ollama\n./run.sh'} />
            <p className="muted">{t('Fully private, but small models reason worse and sometimes fail with tools.')}</p>
          </>
        )}
        {shown === 'api' && (
          <>
            <p><b>{t('Best in-app quality, pay per use:')}</b></p>
            <CopyBlock text={'export ANTHROPIC_API_KEY=sk-ant-...\nexport OPENRUN_MODEL=claude-haiku-5-5   # cheaper\n./run.sh'} />
            <p className="muted">{t('Also:')} <code>OPENRUN_PROVIDER=groq|openrouter|openai</code> {t('with its API key.')}</p>
          </>
        )}
      </div>
    </div>
  )
}

type Settings = { auto_sync: boolean; sync_time: string; auto_adapt: boolean; auto_push: boolean; auto_pace: boolean; heat_adjust: boolean; run_hour: number; lat: number | null; lon: number | null; notify_morning: boolean; notify_analysis: boolean; notify_weekly: boolean }
type DailyLog = { items?: { at: string; steps: { step: string; ok: boolean; result?: unknown; error?: string }[] }[]; last_date?: string }

function Toggle({ label, help, checked, onChange }: { label: string; help: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap', gap: 12, padding: '8px 0', cursor: 'pointer' }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} style={{ marginTop: 2 }} />
      <span><b>{label}</b><br /><span className="small muted">{help}</span></span>
    </label>
  )
}

function summarize(step: { step: string; ok: boolean; result?: unknown; error?: string }) {
  if (!step.ok) return `error: ${step.error}`
  const r = step.result as Record<string, unknown> | unknown[] | null
  if (Array.isArray(r)) return r.length ? t('{n} changes', { n: r.length }) : t('no changes')
  if (r && typeof r === 'object') return Object.entries(r).filter(([, v]) => v !== null && !(Array.isArray(v) && !v.length)).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ') || 'ok'
  return 'ok'
}

function AutomationCard() {
  const { data: st, setData } = useApi<Settings>('/api/settings')
  const log = useApi<DailyLog>('/api/daily/log')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  if (!st) return null
  const save = async (patch: Partial<Settings>) => {
    try { setData(await api.put<Settings>('/api/settings', patch)) } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) }
  }
  const last = log.data?.items?.[log.data.items.length - 1]
  return (
    <div className="card">
      <ConnHead icon="zap" title={t('Daily automation')} status={st.auto_sync ? t('Daily at {time}', { time: st.sync_time }) : t('Off')} tone={st.auto_sync ? 'good' : 'warn'} />
      <p className="small text-2" style={{ marginTop: 10 }}>{t('Every morning: sync Garmin → analyse your workouts → adjust paces → adapt for heat and readiness → send the next 7 days to the watch (only what changed). If the computer was off at that time, it runs when OpenRun starts.')}</p>
      <Toggle label={t('Daily routine')} help={t('Needs OpenRun running (see “Start automatically” below).')} checked={st.auto_sync} onChange={(v) => save({ auto_sync: v })} />
      <div className="row" style={{ paddingLeft: 32, marginBottom: 6 }}>
        <label className="field" style={{ width: 140 }}>{t('Routine time')}<input type="time" value={st.sync_time} onChange={(e) => e.target.value && save({ sync_time: e.target.value })} /></label>
        <label className="field" style={{ width: 160 }}>{t('You usually train at')}
          <select value={st.run_hour} onChange={(e) => save({ run_hour: +e.target.value })}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h}:00</option>)}</select>
        </label>
      </div>
      <Toggle label={t('Send to watch')} help={t('Keeps the next 7 days in the Garmin calendar.')} checked={st.auto_push} onChange={(v) => save({ auto_push: v })} />
      <Toggle label={t('Adjust paces automatically')} help={t('Post-run analysis: VDOT ±0.5 if 2 of the last 3 quality sessions are easier or harder than planned.')} checked={st.auto_pace} onChange={(v) => save({ auto_pace: v })} />
      <Toggle label={t('Heat adjustment')} help={t('Slows the paces according to the forecast temperature + dew point (Open-Meteo) at your training hour.')} checked={st.heat_adjust} onChange={(v) => save({ heat_adjust: v })} />
      <Toggle label={t('Adapt to readiness')} help={t('Low HRV/resting HR/sleep → reduce or change the day\'s session.')} checked={st.auto_adapt} onChange={(v) => save({ auto_adapt: v })} />
      <details style={{ marginTop: 6 }}>
        <summary className="small">{t('Location for the weather')} {st.lat != null ? `(${st.lat.toFixed(2)}, ${st.lon?.toFixed(2)})` : t('(automatic: start of your latest run)')}</summary>
        <div className="row" style={{ marginTop: 8, alignItems: 'flex-end' }}>
          <label className="field" style={{ width: 130 }}>{t('Latitude')}<input type="number" step="0.01" defaultValue={st.lat ?? ''} onBlur={(e) => save({ lat: e.target.value === '' ? null : +e.target.value })} /></label>
          <label className="field" style={{ width: 130 }}>{t('Longitude')}<input type="number" step="0.01" defaultValue={st.lon ?? ''} onBlur={(e) => save({ lon: e.target.value === '' ? null : +e.target.value })} /></label>
          {'geolocation' in navigator && window.isSecureContext && (
            <button className="btn btn-sm" onClick={() => navigator.geolocation.getCurrentPosition((p) => save({ lat: +p.coords.latitude.toFixed(3), lon: +p.coords.longitude.toFixed(3) }))}>{t('Use my location')}</button>
          )}
        </div>
      </details>
      <hr />
      <div className="row spread">
        <span className="small muted">{last ? t('Last routine: {date}', { date: new Date(last.at).toLocaleString(locale()) }) : t('The routine has not run yet.')}</span>
        <button className="btn btn-sm" disabled={busy} onClick={async () => {
          setBusy(true)
          setMsg(null)
          try { await api.post('/api/daily/run'); log.reload(); setMsg({ tone: 'ok', text: t('Routine done.') }) } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) } finally { setBusy(false) }
        }}><Icon name="refresh" size={16} className={busy ? 'spin' : ''} />{busy ? t('Running…') : t('Run now')}</button>
      </div>
      {last && (
        <ul className="small text-2" style={{ margin: '8px 0 0', paddingLeft: 18 }}>
          {last.steps.map((x) => <li key={x.step}><b className={x.ok ? '' : 'bad'}>{x.step}</b>: {summarize(x)}</li>)}
        </ul>
      )}
      {msg && <div style={{ marginTop: 10 }}><Banner tone={msg.tone}>{msg.text}</Banner></div>}
      <details style={{ marginTop: 10 }}>
        <summary className="small">{t('Start automatically at login (macOS)')}</summary>
        <p className="small text-2" style={{ marginTop: 6 }}>{t('For the routine to run every day, OpenRun has to be running. This script registers it with launchd so it starts at login:')}</p>
        <CopyBlock text={t('scripts/install-autostart.sh\n# with access from your phone:\nOPENRUN_PIN=your-pin scripts/install-autostart.sh --lan')} />
        <p className="small muted">{t('Status, restart, PIN change and uninstall: docs/es/arranque-y-movil.md in the repository.')}</p>
      </details>
    </div>
  )
}

function MobileCard() {
  const { data } = useApi<{ lan_enabled: boolean; pin_enabled: boolean; urls: string[]; local: boolean; public?: boolean }>('/api/network')
  if (!data) return null
  if (data.public)
    return (
      <div className="card">
        <ConnHead icon="watch" title={t('OpenRun on your phone')} status={t('On the internet (HTTPS)')} />
        <p className="small text-2" style={{ marginTop: 10 }}>{t('Open this address on your phone, sign in and add it to the home screen:')}</p>
        {data.urls.map((u) => <CopyBlock key={u} text={u} />)}
      </div>
    )
  return (
    <div className="card">
      <ConnHead icon="watch" title={t('OpenRun on your phone')} status={data.lan_enabled ? t('Wi-Fi enabled') : t('This computer only')} tone={data.lan_enabled ? 'good' : 'warn'} />
      {data.lan_enabled ? (
        <>
          <p className="small text-2" style={{ marginTop: 10 }}>{t('With your phone on the same Wi-Fi, open:')}</p>
          {data.urls.map((u) => <CopyBlock key={u} text={u} />)}
          <p className="small muted">{t('It asks for the PIN once. Then: Safari › Share › “Add to Home Screen” (iPhone) or Chrome › “Install app” (Android) and it opens like an app.')}</p>
        </>
      ) : (
        <>
          <p className="small text-2" style={{ marginTop: 10 }}>{t('Right now it only opens on this computer. To use it on your phone (same Wi-Fi), start it with a PIN:')}</p>
          <CopyBlock text={t('OPENRUN_HOST=0.0.0.0 OPENRUN_PIN=your-pin ./run.sh')} />
          <p className="small muted">{t('Away from home: install Tailscale (free) on the computer and the phone and use the Tailscale IP. Don\'t open the port on your router.')}</p>
        </>
      )}
    </div>
  )
}

const b64ToBytes = (b64: string) => {
  const s = atob((b64 + '='.repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(s, (ch) => ch.charCodeAt(0))
}
const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent)

function NotificationsCard() {
  const { data: st, setData } = useApi<Settings>('/api/settings')
  const info = useApi<{ public_key: string; devices: number }>('/api/push')
  const [here, setHere] = useState<boolean | null>(null)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad' | 'info'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  useEffect(() => {
    if (!supported) return
    navigator.serviceWorker.getRegistration('/').then((r) => r?.pushManager.getSubscription()).then((s) => setHere(!!s)).catch(() => setHere(false))
  }, [supported])
  if (!st) return null
  const save = async (patch: Partial<Settings>) => {
    try { setData(await api.put<Settings>('/api/settings', patch)) } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) }
  }
  const enable = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const perm = await Notification.requestPermission()
      if (perm !== 'granted') throw new Error(t('Permission denied. Allow it in the browser settings for this site.'))
      const reg = await navigator.serviceWorker.register('/sw.js')
      await navigator.serviceWorker.ready
      const key = info.data?.public_key ?? (await api.get<{ public_key: string }>('/api/push')).public_key
      const sub = (await reg.pushManager.getSubscription()) ?? await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) })
      await api.post('/api/push/subscribe', sub.toJSON())
      setHere(true)
      info.reload()
      setMsg({ tone: 'ok', text: t('Notifications enabled on this device.') })
    } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) } finally { setBusy(false) }
  }
  const disable = async () => {
    setBusy(true)
    try {
      const sub = await (await navigator.serviceWorker.getRegistration('/'))?.pushManager.getSubscription()
      if (sub) { await api.post('/api/push/unsubscribe', { endpoint: sub.endpoint }); await sub.unsubscribe() }
      setHere(false)
      info.reload()
    } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) } finally { setBusy(false) }
  }
  const needsInstall = isIOS() && !isStandalone()
  return (
    <div className="card stack">
      <ConnHead icon="alert" title={t('Notifications')} status={info.data ? (info.data.devices === 1 ? t('1 device') : t('{n} devices', { n: info.data.devices })) : null} tone={info.data?.devices ? 'good' : 'warn'} />
      <p className="small text-2" style={{ margin: 0 }}>{t('The app\'s own alerts, no Telegram or anything else: your workout in the morning, the analysis when each run syncs and the Monday summary.')}</p>
      {!supported ? <Banner tone="info">{needsInstall ? t('On iPhone: Share › “Add to Home Screen”, open OpenRun from the icon and come back here (iOS 16.4 or later).') : t('This browser does not support push notifications.')}</Banner>
        : needsInstall ? <Banner tone="info">{t('On iPhone, notifications only work with the app added to the home screen: Share › “Add to Home Screen” and open it from the icon.')}</Banner>
          : (
            <div className="row">
              {here ? <button className="btn btn-sm" disabled={busy} onClick={disable}>{t('Turn off on this device')}</button>
                : <button className="btn btn-primary btn-sm" disabled={busy || here === null} onClick={enable}><Icon name="alert" size={16} />{t('Turn on on this device')}</button>}
              {!!info.data?.devices && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={async () => {
                try { await api.post('/api/push/test'); setMsg({ tone: 'ok', text: t('Sent. It should arrive in a few seconds.') }) } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) }
              }}>{t('Send test')}</button>}
            </div>
          )}
      <Toggle label={t('Workout of the day')} help={t('In the morning, after the {time} routine.', { time: st.sync_time })} checked={st.notify_morning} onChange={(v) => save({ notify_morning: v })} />
      <Toggle label={t('Analysis of each run')} help={t('When a new run syncs (Garmin is checked every ~2 h from 9:00 to 22:00).')} checked={st.notify_analysis} onChange={(v) => save({ notify_analysis: v })} />
      <Toggle label={t('Weekly summary')} help={t('On Mondays: how the week went and what to focus on.')} checked={st.notify_weekly} onChange={(v) => save({ notify_weekly: v })} />
      {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
    </div>
  )
}

function AccountCard({ me, onMe }: { me: Me; onMe: () => void }) {
  const acc = useApi<{ ai?: { count: number; limit: number | null } }>('/api/account')
  const [name, setName] = useState(me.name)
  const [cur, setCur] = useState('')
  const [pw, setPw] = useState('')
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const save = async (body: object, ok: string) => {
    setMsg(null)
    try { await api.put('/api/account', body); setMsg({ tone: 'ok', text: ok }); setCur(''); setPw(''); onMe() } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) }
  }
  return (
    <div className="card stack">
      <ConnHead icon="user" title={t('Your account')} status={me.is_admin ? t('Administrator') : null} />
      <p className="small text-2" style={{ margin: 0 }}>{t('Username')} <b>{me.username}</b>. {t('Your data, your plan, your Garmin and your coach chat are yours alone.')}</p>
      {acc.data?.ai && (
        <div className="small text-2">{t('AI coach today:')} <b className="num">{acc.data.ai.count}</b> {acc.data.ai.limit != null ? t('of {n} requests (resets daily)', { n: acc.data.ai.limit }) : t('requests (no limit)')}</div>
      )}
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="field grow">{t('Name')}<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <button className="btn btn-sm" disabled={!name.trim() || name === me.name} onClick={() => save({ name }, t('Name saved'))}>{t('Save')}</button>
      </div>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save({ current_password: cur, new_password: pw }, t('Password changed. Your other devices will have to sign in again.')) }}>
        <input type="text" autoComplete="username" value={me.username} readOnly hidden />
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
          <label className="field">{t('Current password')}<input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></label>
          <label className="field">{t('New password')}<input type="password" autoComplete="new-password" minLength={10} value={pw} onChange={(e) => setPw(e.target.value)} /></label>
        </div>
        <div className="row">
          <button className="btn btn-sm" disabled={!pw}>{t('Change password')}</button>
          <span className="grow" />
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => api.post('/api/auth/logout').then(() => { window.location.hash = ''; window.location.reload() })}>{t('Sign out')}</button>
        </div>
      </form>
      {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
    </div>
  )
}

type Invite = { code: string; note: string | null; expires_at: string }
type UserRow = Me & { created_at: string; activities: number; ai_today: number; ai_limit: number | null; ai_limit_custom: boolean }

function AiLimit({ u, def, onSaved }: { u: UserRow; def: number; onSaved: () => void }) {
  const [v, setV] = useState(u.ai_limit_custom ? String(u.ai_limit ?? '') : '')
  const save = () => api.put(`/api/users/${u.id}/limits`, { ai_daily_limit: v.trim() === '' ? null : +v }).then(onSaved)
  return (
    <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
      <span className="num small" title={t('AI coach requests today')}>{u.ai_today}/{u.ai_limit ?? '∞'}</span>
      <input aria-label={t('Daily AI limit for {user}', { user: u.username })} className="input-xs" inputMode="numeric" placeholder={u.is_admin ? '∞' : String(def)}
        value={v} onChange={(e) => setV(e.target.value.replace(/\D/g, ''))} onBlur={save} onKeyDown={(e) => { if (e.key === 'Enter') save() }} />
    </div>
  )
}

function UsersCard({ me }: { me: Me }) {
  const { data, reload } = useApi<{ users: UserRow[]; invites: Invite[]; ai_default_limit: number }>('/api/users')
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const link = (c: string) => `${window.location.origin}/#invitacion=${c}`
  if (!data) return null
  return (
    <div className="card stack">
      <ConnHead icon="user" title={t('Users')} status={`${data.users.length}`} />
      <p className="small text-2" style={{ margin: 0 }}>{t('Invite other people: each gets their own plan, Garmin and coach. The link works once and expires in 14 days.')}</p>
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="field grow">{t('For whom (optional)')}<input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('e.g. Sam')} /></label>
        <button className="btn btn-primary btn-sm" onClick={async () => {
          setErr(null)
          try { await api.post('/api/users/invites', { note }); setNote(''); reload() } catch (e) { setErr((e as Error).message) }
        }}><Icon name="plus" size={16} />{t('Create invitation')}</button>
      </div>
      {data.invites.map((i) => (
        <div key={i.code} className="stack" style={{ gap: 4 }}>
          <div className="row small"><b className="grow">{i.note || t('Invitation')}</b><span className="muted">{t('expires {date}', { date: fmtDate(i.expires_at.slice(0, 10)) })}</span>
            <button className="btn btn-ghost btn-icon btn-sm" aria-label={t('Revoke invitation')} onClick={() => api.del(`/api/users/invites/${i.code}`).then(reload)}><Icon name="trash" size={16} /></button>
          </div>
          <CopyBlock text={link(i.code)} />
        </div>
      ))}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>{t('User')}</th><th className="hide-sm">{t('Joined')}</th><th className="hide-sm">{t('Activities')}</th><th>{t('AI today / limit')}</th><th /></tr></thead>
          <tbody>
            {data.users.map((u) => (
              <tr key={u.id}>
                <td><b>{u.name || u.username}</b><div className="small muted">{u.username}{u.is_admin ? ' · admin' : ''}</div></td>
                <td className="hide-sm">{u.created_at ? fmtDate(u.created_at.slice(0, 10)) : '—'}</td>
                <td className="hide-sm">{u.activities}</td>
                <td><AiLimit u={u} def={data.ai_default_limit} onSaved={reload} /></td>
                <td>{u.id !== me.id && (
                  <button className="btn btn-ghost btn-icon btn-sm" aria-label={t('Delete {user}', { user: u.username })} onClick={async () => {
                    if (!confirm(t('Delete the account of {user} and ALL their data? This cannot be undone.', { user: u.username }))) return
                    try { await api.del(`/api/users/${u.id}`); reload() } catch (e) { setErr((e as Error).message) }
                  }}><Icon name="trash" size={16} /></button>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small muted" style={{ margin: 0 }}>{t('AI limit: daily requests to the coach (chat, weekly summary, explanations). Empty = default ({n}/day; administrators unlimited). Protects the provider’s free quota.', { n: data.ai_default_limit })}</p>
      {err && <Banner tone="bad">{err}</Banner>}
    </div>
  )
}

function ThemeCard() {
  const [theme, setTheme] = useState<'system' | 'light' | 'dark'>(() => {
    try { return (localStorage.getItem('theme') as 'light' | 'dark') || 'system' } catch { return 'system' }
  })
  useEffect(() => {
    if (theme === 'system') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', theme)
    try { if (theme === 'system') localStorage.removeItem('theme'); else localStorage.setItem('theme', theme) } catch { /* private mode */ }
  }, [theme])
  return (
    <div className="card">
      <ConnHead icon={theme === 'dark' ? 'moon' : 'sun'} title={t('Appearance and language')} status={null} />
      <div style={{ marginTop: 12 }}>
        <Segmented label={t('Theme')} value={theme} onChange={setTheme} options={[['system', t('System')], ['light', t('Light')], ['dark', t('Dark')]]} />
      </div>
      <div style={{ marginTop: 12 }}>
        <Segmented label={t('Language')} value={getLang()} options={LANGS}
          onChange={(l: Lang) => { api.put('/api/account', { lang: l }).catch(() => {}).finally(() => setLang(l)) }} />
      </div>
    </div>
  )
}

function SupportCard() {
  return (
    <div className="card">
      <ConnHead icon="heart" title={t('Support OpenRun')} status={null} />
      <p className="small text-2" style={{ marginTop: 10 }}>{t('OpenRun is free and open source, made in spare time. If it helps your training, you can buy the developer a coffee: it pays for the time and keeps the project going.')}</p>
      <div className="row">
        <a className="btn btn-primary" href={DONATE_URL} target="_blank" rel="noreferrer"><Icon name="heart" />{t('Buy me a coffee')}</a>
        <a className="btn btn-ghost" href={REPO_URL} target="_blank" rel="noreferrer"><Icon name="external" />{t('Code, ideas and bugs on GitHub')}</a>
      </div>
    </div>
  )
}

export default function SettingsPage({ onChange, me, onMe }: { onChange: () => void; me: Me | null; onMe: () => void }) {
  return (
    <div className="stack" style={{ maxWidth: 820 }}>
      {me && <AccountCard me={me} onMe={onMe} />}
      <GarminCard onChange={onChange} />
      <HelioCard />
      <AutomationCard />
      <NotificationsCard />
      <MobileCard />
      <CoachCard />
      <HistoryImportCard />
      <ProfileCard />
      <ImportCard />
      <ThemeCard />
      <SupportCard />
      {me?.is_admin && <UsersCard me={me} />}
      <p className="small muted">OpenRun · {t('only you can see your data')} · {fmtDate(new Date().toISOString().slice(0, 10), { year: 'numeric' })}</p>
    </div>
  )
}
