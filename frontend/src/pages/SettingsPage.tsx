import { useEffect, useRef, useState } from 'react'
import { api, fmtDate, useApi } from '../api'
import type { Me } from '../App'
import { Banner, Icon, Segmented, type IconName } from '../ui'

type Athlete = { name: string; sex: string; age: number | null; max_hr: number | null; rest_hr: number | null; lthr: number | null; vdot: number | null; vdot_source: string | null; hr_zones?: { zone: number; low: number; high: number }[] }
type GStatus = { connected: boolean; name?: string; needs_mfa?: boolean; error?: string; last_sync?: string | null }
type CoachInfo = { provider: string; model: string; configured: boolean
  mcp: { remote: false; command: string; args: string[]; cwd: string } | { remote: true; url: string; token_set: boolean } }

function ConnHead({ icon, title, status, tone = 'good' }: { icon: IconName; title: string; status: string | null; tone?: 'good' | 'warn' }) {
  return (
    <div className="row" style={{ flexWrap: 'nowrap' }}>
      <div style={{ width: 48, height: 48, borderRadius: 12, background: 'var(--surface-2)', display: 'grid', placeItems: 'center', flex: 'none' }}><Icon name={icon} size={24} /></div>
      <h3 className="grow">{title}</h3>
      {status && <span className={`chip chip-${tone}`}>{status}</span>}
    </div>
  )
}

function GarminCard({ onChange }: { onChange: () => void }) {
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
      <ConnHead icon="watch" title="Garmin Forerunner 265" status={st ? (st.connected ? 'Conectado' : 'Desconectado') : null} tone={st?.connected ? 'good' : 'warn'} />
      <div style={{ marginTop: 12 }}>
        {st?.connected ? (
          <>
            <p className="small text-2">Conectado{st.name ? ` como ${st.name}` : ''}. Último sync: {st.last_sync ? new Date(st.last_sync).toLocaleString('es-ES') : 'nunca'}.</p>
            <div className="row">
              <button className="btn" disabled={busy} onClick={async () => {
                setBusy(true)
                setMsg({ tone: 'info', text: 'Descargando todo el histórico…' })
                try {
                  const r = await api.post<{ activities: number }>('/api/garmin/sync?days=14&full=true')
                  setMsg({ tone: 'ok', text: `${r.activities} actividades sincronizadas (histórico completo).` })
                  load(); onChange()
                } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) } finally { setBusy(false) }
              }}><Icon name="refresh" />Sincronizar histórico completo</button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => go(async () => { await api.post('/api/garmin/logout'); return { connected: false } })}>Desconectar</button>
            </div>
          </>
        ) : st?.needs_mfa ? (
          <form className="row" style={{ alignItems: 'flex-end' }} onSubmit={(e) => { e.preventDefault(); go(() => api.post('/api/garmin/mfa', { code })) }}>
            <label className="field" style={{ maxWidth: 200 }}>Código de verificación
              <input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
            </label>
            <button className="btn btn-primary" disabled={busy}>Verificar</button>
          </form>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); go(() => api.post('/api/garmin/login', { email, password: pw })) }}>
            <p className="small muted">La contraseña no se guarda: solo los tokens de sesión, en tu equipo (~/.openrun/garmin). API no oficial de Garmin.</p>
            <div className="form-grid">
              <label className="field">Email de Garmin Connect
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
              </label>
              <label className="field">Contraseña
                <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" />
              </label>
            </div>
            <button className="btn btn-primary" style={{ marginTop: 12 }} disabled={busy}>{busy ? 'Conectando…' : 'Conectar'}</button>
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
    const t = setInterval(async () => {
      s -= 1
      setLeft(s)
      if (s > 0) return
      clearInterval(t)
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
      <ConnHead icon="heart" title="Amazfit Helio Strap" status={state === 'idle' ? null : 'Conectada'} />
      <details style={{ marginTop: 10 }}>
        <summary className="small">Cómo usarla con el Forerunner 265</summary>
        <p className="small text-2" style={{ marginTop: 6 }}>
        <strong>En carrera:</strong> activa “Compartir frecuencia cardíaca” en la Helio Strap (app Zepp) y emparéjala en el Forerunner 265 como sensor de FC
        (Ajustes › Sensores y accesorios › Añadir). Garmin grabará la FC de la banda y llegará aquí con el sync.<br />
        <strong>HRV matinal:</strong> al despertar, tumbado, conecta aquí y mide 3 min (Chrome/Edge, Web Bluetooth).
        </p>
      </details>
      {!bt ? <div style={{ marginTop: 12 }}><Banner>Este navegador no soporta Web Bluetooth. Usa Chrome o Edge.</Banner></div> : (
        <div className="row" style={{ marginTop: 12 }}>
          {state === 'idle' && <button className="btn btn-primary" onClick={connect}><Icon name="bluetooth" />Conectar banda</button>}
          {state !== 'idle' && <span className="stat-value" style={{ margin: 0 }}>{hr ?? '–'}<small>ppm</small></span>}
          {state === 'connected' && <button className="btn btn-primary" onClick={measure} disabled={!hasRR}>{hasRR ? 'Medir HRV (3 min)' : 'Esperando intervalos RR…'}</button>}
          {state === 'measuring' && (
            <div className="grow" style={{ maxWidth: 260 }}>
              <div className="small">Quieto y respirando normal… {left} s</div>
              <div className="progress" style={{ marginTop: 6 }}><span style={{ width: `${((180 - left) / 180) * 100}%` }} /></div>
            </div>
          )}
          {state !== 'idle' && <button className="btn btn-ghost" onClick={() => devRef.current?.gatt?.disconnect()}>Desconectar</button>}
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
      setRes({ tone: 'ok', text: `${r.imported_days} días importados.` })
    } catch (e) {
      setRes({ tone: 'bad', text: (e as Error).message })
    }
  }
  return (
    <div className="card">
      <ConnHead icon="heart" title="Importar datos de Zepp (HRV, sueño)" status={null} />
      <p className="small text-2" style={{ marginTop: 10 }}>En la app Zepp: Perfil › Ajustes › Cuenta › Exportar datos. Sube el .zip o un CSV con fecha + HRV / FC reposo / sueño.</p>
      <label className="field" style={{ maxWidth: 360 }}>Archivo
        <input type="file" accept=".zip,.csv" style={{ paddingTop: 9 }} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </label>
      {res && <div style={{ marginTop: 10 }}><Banner tone={res.tone}>{res.text}</Banner></div>}
    </div>
  )
}

type ImportJob = { id: string; state: 'running' | 'done' | 'error'; file: number; files: number; done: number; total: number; error: string | null
  stats: { imported?: number; duplicates?: number; with_efforts?: number; oldest?: string | null; newest?: string | null } }

function HistoryImportCard() {
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
      <ConnHead icon="upload" title="Importar histórico (Strava, FIT, GPX, TCX)" status={null} />
      <p className="small text-2" style={{ marginTop: 10 }}>
        Trae tus carreras de años anteriores para tener récords y tendencia completos. Se calculan los mejores tramos (1K, milla, 5K, 10K, media, maratón) de cada actividad y se ignoran las que ya están en Garmin.
      </p>
      <details style={{ marginBottom: 10 }}>
        <summary className="small">Cómo conseguir tus archivos</summary>
        <ul className="small text-2" style={{ margin: '6px 0 0', paddingLeft: 18 }}>
          <li><b>Strava:</b> strava.com › Ajustes › Mi cuenta › «Descarga o elimina tu cuenta» › <i>Solicitar archivo</i>. Llega un email con un .zip: súbelo tal cual (pueden ser varios GB; tarda unos minutos).</li>
          <li><b>Garmin (exportación completa):</b> Garmin Account › Privacidad › Exportar datos. Sube el .zip.</li>
          <li><b>Sueltos:</b> archivos .fit, .gpx o .tcx (también .gz) de cualquier reloj o app.</li>
        </ul>
      </details>
      <label className="field" style={{ maxWidth: 420 }}>Archivos
        <input type="file" multiple accept=".zip,.fit,.gpx,.tcx,.gz" style={{ paddingTop: 9 }} disabled={uploading || job?.state === 'running'}
          onChange={(e) => e.target.files?.length && upload(e.target.files)} />
      </label>
      {uploading && <div style={{ marginTop: 10 }}><Banner tone="info">Subiendo…</Banner></div>}
      {job?.state === 'running' && (
        <div style={{ marginTop: 12 }} aria-live="polite">
          <div className="small">Procesando{job.files > 1 ? ` archivo ${job.file}/${job.files}` : ''}: {job.done}/{job.total || '…'} · {st.imported ?? 0} carreras importadas</div>
          <div className="progress" style={{ marginTop: 6 }}><span style={{ width: `${pct}%` }} /></div>
        </div>
      )}
      {job?.state === 'done' && (
        <div style={{ marginTop: 12 }}>
          <Banner tone="ok">
            {st.imported ?? 0} carreras importadas{st.oldest ? ` (${fmtDate(st.oldest, { month: 'short', year: 'numeric' })} – ${fmtDate(st.newest ?? st.oldest, { month: 'short', year: 'numeric' })})` : ''}, {st.with_efforts ?? 0} con tramos para récords, {st.duplicates ?? 0} ya existían.{' '}
            <a href="#progreso">Ver récords</a>
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
      <ConnHead icon="user" title="Perfil y zonas" status={a.vdot ? `VDOT ${a.vdot}` : null} />
      <div className="form-grid" style={{ marginTop: 14 }}>
        <label className="field">Sexo<select value={a.sex} onChange={(e) => setA({ ...a, sex: e.target.value })}><option value="male">Hombre</option><option value="female">Mujer</option></select></label>
        <label className="field">Edad<input type="number" inputMode="numeric" value={a.age ?? ''} onChange={(e) => setA({ ...a, age: num(e.target.value) })} /></label>
        <label className="field">FC máxima<input type="number" inputMode="numeric" value={a.max_hr ?? ''} onChange={(e) => setA({ ...a, max_hr: num(e.target.value) })} /></label>
        <label className="field">FC en reposo<input type="number" inputMode="numeric" value={a.rest_hr ?? ''} onChange={(e) => setA({ ...a, rest_hr: num(e.target.value) })} /></label>
        <label className="field">FC umbral (LTHR)<input type="number" inputMode="numeric" value={a.lthr ?? ''} onChange={(e) => setA({ ...a, lthr: num(e.target.value) })} /></label>
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn btn-primary" onClick={() => api.put<Athlete>('/api/athlete', a).then((r) => { setA(r); setMsg({ tone: 'ok', text: 'Guardado' }) })}>Guardar</button>
        {a.vdot_source && <span className="small muted">VDOT {a.vdot} · origen: {a.vdot_source}</span>}
      </div>
      {a.hr_zones && (
        <div style={{ marginTop: 14 }}>
          <div className="micro" style={{ marginBottom: 6 }}>Zonas de FC</div>
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
      <h3>Nueva marca o test</h3>
      <p className="small muted">Recalcula tu VDOT y los ritmos de todos los entrenos futuros (también los ya enviados al reloj).</p>
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="field" style={{ width: 140 }}>Distancia
          <select value={race.distance} onChange={(e) => setRace({ ...race, distance: e.target.value })}>
            {[['mile', 'Milla'], ['3k', '3K'], ['5k', '5K'], ['10k', '10K'], ['15k', '15K'], ['half', 'Media'], ['marathon', 'Maratón']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="field" style={{ width: 160 }}>Tiempo<input placeholder="mm:ss o h:mm:ss" value={race.time} onChange={(e) => setRace({ ...race, time: e.target.value })} /></label>
        <button className="btn" disabled={!race.time} onClick={() => api.post<{ vdot: number; workouts_updated: number; garmin_updated?: number }>('/api/athlete/race-result', { ...race, recalibrate: true })
          .then((r) => { setMsg({ tone: 'ok', text: `VDOT ${r.vdot} · ${r.workouts_updated} entrenos re-ajustados${r.garmin_updated ? ` · ${r.garmin_updated} actualizados en Garmin` : ''}` }); setA({ ...a, vdot: r.vdot }) })
          .catch((e) => setMsg({ tone: 'bad', text: e.message }))}>Aplicar</button>
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
        {ok ? 'Copiado' : 'Copiar'}
      </button>
    </div>
  )
}

function CoachCard() {
  const { data } = useApi<CoachInfo>('/api/coach/info')
  const [tab, setTab] = useState<'mcp' | 'nvidia' | 'gemini' | 'ollama' | 'api' | null>(null)
  if (!data) return null
  const shown = tab ?? (['nvidia', 'gemini', 'ollama'].includes(data.provider) ? data.provider as 'nvidia' | 'gemini' | 'ollama' : data.provider === 'anthropic' ? 'api' : 'nvidia')
  const server = data.mcp.remote
    ? { command: '/Users/<tu-usuario>/OpenRun/backend/.venv/bin/python', args: ['-m', 'app.mcp_server'],
        env: { PYTHONPATH: '/Users/<tu-usuario>/OpenRun/backend', OPENRUN_URL: data.mcp.url, OPENRUN_API_TOKEN: '<OPENRUN_API_TOKEN del servidor>' } }
    : { command: data.mcp.command, args: data.mcp.args, env: { PYTHONPATH: data.mcp.cwd } }
  const claudeCfg = JSON.stringify({ mcpServers: { openrun: server } }, null, 2)
  return (
    <div className="card">
      <ConnHead icon="sparkles" title="Coach IA" status={`${data.provider} · ${data.configured ? 'listo' : 'sin configurar'}`} tone={data.configured ? 'good' : 'warn'} />
      <p className="small text-2" style={{ marginTop: 10 }}>El coach funciona dentro de OpenRun con el proveedor que configures en el servidor. Las herramientas y reglas son las mismas en todos los casos.</p>
      <Segmented label="Opción de coach" value={shown} onChange={setTab}
        options={[['nvidia', 'NVIDIA gratis'], ['gemini', 'Gemini gratis'], ['api', 'API de pago'], ['ollama', 'Ollama local'], ['mcp', 'Fuera de la app (MCP)']]} />
      <div style={{ marginTop: 12 }} className="small">
        {shown === 'mcp' && (
          <>
            <p><b>Sin coste extra con Claude (Free/Pro/Max):</b> conecta OpenRun como servidor MCP en <b>Claude Desktop</b> y chatea allí; Claude usará tus datos y creará entrenos que aparecen aquí. Ajustes de Claude Desktop › Desarrollador › Editar config y añade:</p>
            {data.mcp.remote && <p className="muted">OpenRun está en un servidor: el MCP se ejecuta en tu ordenador (desde un clon del repo) y habla con el servidor usando el token de API.{!data.mcp.token_set && ' El servidor aún no tiene OPENRUN_API_TOKEN configurado.'}</p>}
            <CopyBlock text={claudeCfg} />
            <p className="muted">Reinicia Claude Desktop. También funciona con <b>Gemini CLI</b> (gratis con cuenta Google) en <code>~/.gemini/settings.json</code> con el mismo bloque <code>mcpServers</code>. Las suscripciones de ChatGPT/Claude/Gemini no dan acceso a la API para apps propias: por eso se usa MCP.</p>
          </>
        )}
        {shown === 'nvidia' && (
          <>
            <p><b>Chat dentro de OpenRun gratis con NVIDIA:</b> crea una cuenta en build.nvidia.com (NVIDIA Developer, verificación por teléfono, sin tarjeta), genera una API key (<code>nvapi-…</code>) y configura:</p>
            <CopyBlock text={'OPENRUN_PROVIDER=nvidia\nNVIDIA_API_KEY=nvapi-...\n# opcional: OPENRUN_MODEL=minimaxai/minimax-m3.1-flash (por defecto)'} />
            <p className="muted">~40 peticiones por minuto (cada respuesta del coach puede usar varias). Condiciones de prueba/evaluación: NVIDIA puede limitar o cortar el acceso. En el servidor, ponlas como variables de entorno en Coolify.</p>
          </>
        )}
        {shown === 'gemini' && (
          <>
            <p><b>Chat dentro de OpenRun gratis:</b> crea una API key en Google AI Studio (plan gratuito con límites diarios) y arranca con:</p>
            <CopyBlock text={'export OPENRUN_PROVIDER=gemini\nexport GEMINI_API_KEY=...\n./run.sh'} />
            <p className="muted">Ojo: en el plan gratuito Google puede usar las conversaciones para mejorar sus productos (son datos de salud).</p>
          </>
        )}
        {shown === 'ollama' && (
          <>
            <p><b>100 % local y gratis:</b> instala Ollama y un modelo con soporte de herramientas (p. ej. <code>qwen3:8b</code>, ~5 GB):</p>
            <CopyBlock text={'ollama pull qwen3:8b\nexport OPENRUN_PROVIDER=ollama\n./run.sh'} />
            <p className="muted">Privacidad total, pero los modelos pequeños razonan peor y a veces fallan con las herramientas.</p>
          </>
        )}
        {shown === 'api' && (
          <>
            <p><b>Mejor calidad dentro de la app, pago por uso:</b></p>
            <CopyBlock text={'export ANTHROPIC_API_KEY=sk-ant-...\nexport OPENRUN_MODEL=claude-haiku-5-5   # más barato\n./run.sh'} />
            <p className="muted">También: <code>OPENRUN_PROVIDER=groq|openrouter|openai</code> con su API key.</p>
          </>
        )}
      </div>
    </div>
  )
}

type Settings = { auto_sync: boolean; sync_time: string; auto_adapt: boolean; auto_push: boolean; auto_pace: boolean; heat_adjust: boolean; run_hour: number; lat: number | null; lon: number | null }
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
  if (Array.isArray(r)) return r.length ? `${r.length} cambios` : 'sin cambios'
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
      <ConnHead icon="zap" title="Automatización diaria" status={st.auto_sync ? `Cada día ${st.sync_time}` : 'Desactivada'} tone={st.auto_sync ? 'good' : 'warn'} />
      <p className="small text-2" style={{ marginTop: 10 }}>Cada mañana: sincroniza Garmin → analiza tus entrenos → ajusta ritmos → adapta por calor y readiness → manda los próximos 7 días al reloj (solo lo que cambió). Si el ordenador estaba apagado a esa hora, se hace al arrancar OpenRun.</p>
      <Toggle label="Rutina diaria" help="Necesita OpenRun en marcha (ver «Arranque automático» abajo)." checked={st.auto_sync} onChange={(v) => save({ auto_sync: v })} />
      <div className="row" style={{ paddingLeft: 32, marginBottom: 6 }}>
        <label className="field" style={{ width: 140 }}>Hora de la rutina<input type="time" value={st.sync_time} onChange={(e) => e.target.value && save({ sync_time: e.target.value })} /></label>
        <label className="field" style={{ width: 160 }}>Sueles entrenar a las
          <select value={st.run_hour} onChange={(e) => save({ run_hour: +e.target.value })}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h}:00</option>)}</select>
        </label>
      </div>
      <Toggle label="Enviar al reloj" help="Mantiene los próximos 7 días en el calendario de Garmin." checked={st.auto_push} onChange={(v) => save({ auto_push: v })} />
      <Toggle label="Ajustar ritmos automáticamente" help="Análisis post-entreno: VDOT ±0,5 si 2 de las 3 últimas sesiones de calidad salen más fáciles o más duras." checked={st.auto_pace} onChange={(v) => save({ auto_pace: v })} />
      <Toggle label="Ajuste por calor" help="Ralentiza los ritmos según temperatura + punto de rocío previstos (Open-Meteo) a tu hora de entreno." checked={st.heat_adjust} onChange={(v) => save({ heat_adjust: v })} />
      <Toggle label="Adaptar a la readiness" help="HRV/FC en reposo/sueño bajos → reduce o cambia la sesión del día." checked={st.auto_adapt} onChange={(v) => save({ auto_adapt: v })} />
      <details style={{ marginTop: 6 }}>
        <summary className="small">Ubicación para el tiempo {st.lat != null ? `(${st.lat.toFixed(2)}, ${st.lon?.toFixed(2)})` : '(automática: inicio de tu última carrera)'}</summary>
        <div className="row" style={{ marginTop: 8, alignItems: 'flex-end' }}>
          <label className="field" style={{ width: 130 }}>Latitud<input type="number" step="0.01" defaultValue={st.lat ?? ''} onBlur={(e) => save({ lat: e.target.value === '' ? null : +e.target.value })} /></label>
          <label className="field" style={{ width: 130 }}>Longitud<input type="number" step="0.01" defaultValue={st.lon ?? ''} onBlur={(e) => save({ lon: e.target.value === '' ? null : +e.target.value })} /></label>
          {'geolocation' in navigator && window.isSecureContext && (
            <button className="btn btn-sm" onClick={() => navigator.geolocation.getCurrentPosition((p) => save({ lat: +p.coords.latitude.toFixed(3), lon: +p.coords.longitude.toFixed(3) }))}>Usar mi ubicación</button>
          )}
        </div>
      </details>
      <hr />
      <div className="row spread">
        <span className="small muted">{last ? `Última rutina: ${new Date(last.at).toLocaleString('es-ES')}` : 'La rutina aún no se ha ejecutado.'}</span>
        <button className="btn btn-sm" disabled={busy} onClick={async () => {
          setBusy(true)
          setMsg(null)
          try { await api.post('/api/daily/run'); log.reload(); setMsg({ tone: 'ok', text: 'Rutina ejecutada.' }) } catch (e) { setMsg({ tone: 'bad', text: (e as Error).message }) } finally { setBusy(false) }
        }}><Icon name="refresh" size={16} className={busy ? 'spin' : ''} />{busy ? 'Ejecutando…' : 'Ejecutar ahora'}</button>
      </div>
      {last && (
        <ul className="small text-2" style={{ margin: '8px 0 0', paddingLeft: 18 }}>
          {last.steps.map((x) => <li key={x.step}><b className={x.ok ? '' : 'bad'}>{x.step}</b>: {summarize(x)}</li>)}
        </ul>
      )}
      {msg && <div style={{ marginTop: 10 }}><Banner tone={msg.tone}>{msg.text}</Banner></div>}
      <details style={{ marginTop: 10 }}>
        <summary className="small">Arranque automático al iniciar sesión (macOS)</summary>
        <p className="small text-2" style={{ marginTop: 6 }}>Para que la rutina se ejecute cada día, OpenRun tiene que estar arrancado. Este script lo registra en launchd para que arranque solo al iniciar sesión:</p>
        <CopyBlock text={'scripts/install-autostart.sh\n# con acceso desde el móvil:\nOPENRUN_PIN=tu-pin scripts/install-autostart.sh --lan'} />
        <p className="small muted">Estado, reinicio, cambio de PIN y desinstalación: docs/AUTOSTART_Y_MOVIL.md en el repositorio.</p>
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
        <ConnHead icon="watch" title="OpenRun en el móvil" status="En internet (HTTPS)" />
        <p className="small text-2" style={{ marginTop: 10 }}>Abre esta dirección en el móvil, inicia sesión y añádela a la pantalla de inicio:</p>
        {data.urls.map((u) => <CopyBlock key={u} text={u} />)}
      </div>
    )
  return (
    <div className="card">
      <ConnHead icon="watch" title="OpenRun en el móvil" status={data.lan_enabled ? 'Wifi activado' : 'Solo este ordenador'} tone={data.lan_enabled ? 'good' : 'warn'} />
      {data.lan_enabled ? (
        <>
          <p className="small text-2" style={{ marginTop: 10 }}>Con el móvil en la misma wifi abre:</p>
          {data.urls.map((u) => <CopyBlock key={u} text={u} />)}
          <p className="small muted">Te pedirá el PIN una vez. Luego: Safari › Compartir › «Añadir a pantalla de inicio» (iPhone) o Chrome › «Instalar app» (Android) y se abre como una app.</p>
        </>
      ) : (
        <>
          <p className="small text-2" style={{ marginTop: 10 }}>Ahora solo se puede abrir desde este ordenador. Para usarla en el móvil (misma wifi), arranca con un PIN:</p>
          <CopyBlock text={'OPENRUN_HOST=0.0.0.0 OPENRUN_PIN=tu-pin ./run.sh'} />
          <p className="small muted">Fuera de casa: instala Tailscale (gratis) en el Mac y el móvil y usa la IP de Tailscale. No abras el puerto en el router.</p>
        </>
      )}
    </div>
  )
}

function AccountCard({ me, onMe }: { me: Me; onMe: () => void }) {
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
      <ConnHead icon="user" title="Tu cuenta" status={me.is_admin ? 'Administrador' : null} />
      <p className="small text-2" style={{ margin: 0 }}>Usuario <b>{me.username}</b>. Tus datos, tu plan, tu Garmin y tu chat con el coach son solo tuyos.</p>
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="field grow">Nombre<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <button className="btn btn-sm" disabled={!name.trim() || name === me.name} onClick={() => save({ name }, 'Nombre guardado')}>Guardar</button>
      </div>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save({ current_password: cur, new_password: pw }, 'Contraseña cambiada. Los demás dispositivos tendrán que volver a entrar.') }}>
        <input type="text" autoComplete="username" value={me.username} readOnly hidden />
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
          <label className="field">Contraseña actual<input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></label>
          <label className="field">Nueva contraseña<input type="password" autoComplete="new-password" minLength={10} value={pw} onChange={(e) => setPw(e.target.value)} /></label>
        </div>
        <div className="row">
          <button className="btn btn-sm" disabled={!pw}>Cambiar contraseña</button>
          <span className="grow" />
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => api.post('/api/auth/logout').then(() => { window.location.hash = ''; window.location.reload() })}>Cerrar sesión</button>
        </div>
      </form>
      {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
    </div>
  )
}

type Invite = { code: string; note: string | null; expires_at: string }
type UserRow = Me & { created_at: string; activities: number }

function UsersCard({ me }: { me: Me }) {
  const { data, reload } = useApi<{ users: UserRow[]; invites: Invite[] }>('/api/users')
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const link = (c: string) => `${window.location.origin}/#invitacion=${c}`
  if (!data) return null
  return (
    <div className="card stack">
      <ConnHead icon="user" title="Usuarios" status={`${data.users.length}`} />
      <p className="small text-2" style={{ margin: 0 }}>Invita a otras personas: cada una tendrá su propio plan, su Garmin y su coach. El enlace sirve una sola vez y caduca en 14 días.</p>
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="field grow">Para quién (opcional)<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="p. ej. Ana" /></label>
        <button className="btn btn-primary btn-sm" onClick={async () => {
          setErr(null)
          try { await api.post('/api/users/invites', { note }); setNote(''); reload() } catch (e) { setErr((e as Error).message) }
        }}><Icon name="plus" size={16} />Crear invitación</button>
      </div>
      {data.invites.map((i) => (
        <div key={i.code} className="stack" style={{ gap: 4 }}>
          <div className="row small"><b className="grow">{i.note || 'Invitación'}</b><span className="muted">caduca {fmtDate(i.expires_at.slice(0, 10))}</span>
            <button className="btn btn-ghost btn-icon btn-sm" aria-label="Anular invitación" onClick={() => api.del(`/api/users/invites/${i.code}`).then(reload)}><Icon name="trash" size={16} /></button>
          </div>
          <CopyBlock text={link(i.code)} />
        </div>
      ))}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Usuario</th><th className="hide-sm">Alta</th><th>Actividades</th><th /></tr></thead>
          <tbody>
            {data.users.map((u) => (
              <tr key={u.id}>
                <td><b>{u.name || u.username}</b><div className="small muted">{u.username}{u.is_admin ? ' · admin' : ''}</div></td>
                <td className="hide-sm">{u.created_at ? fmtDate(u.created_at.slice(0, 10)) : '—'}</td>
                <td>{u.activities}</td>
                <td>{u.id !== me.id && (
                  <button className="btn btn-ghost btn-icon btn-sm" aria-label={`Borrar ${u.username}`} onClick={async () => {
                    if (!confirm(`¿Borrar la cuenta de ${u.username} y TODOS sus datos? No se puede deshacer.`)) return
                    try { await api.del(`/api/users/${u.id}`); reload() } catch (e) { setErr((e as Error).message) }
                  }}><Icon name="trash" size={16} /></button>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {err && <Banner tone="bad">{err}</Banner>}
    </div>
  )
}

function ThemeCard() {
  const [t, setT] = useState<'system' | 'light' | 'dark'>(() => {
    try { return (localStorage.getItem('theme') as 'light' | 'dark') || 'system' } catch { return 'system' }
  })
  useEffect(() => {
    if (t === 'system') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', t)
    try { if (t === 'system') localStorage.removeItem('theme'); else localStorage.setItem('theme', t) } catch { /* private mode */ }
  }, [t])
  return (
    <div className="card">
      <ConnHead icon={t === 'dark' ? 'moon' : 'sun'} title="Apariencia" status={null} />
      <div style={{ marginTop: 12 }}>
        <Segmented label="Tema" value={t} onChange={setT} options={[['system', 'Sistema'], ['light', 'Claro'], ['dark', 'Oscuro']]} />
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
      <MobileCard />
      <CoachCard />
      <HistoryImportCard />
      <ProfileCard />
      <ImportCard />
      <ThemeCard />
      {me?.is_admin && <UsersCard me={me} />}
      <p className="small muted">OpenRun · tus datos solo los ves tú · {fmtDate(new Date().toISOString().slice(0, 10), { year: 'numeric' })}</p>
    </div>
  )
}
