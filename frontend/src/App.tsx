import { useCallback, useEffect, useState } from 'react'
import { api, type Plan } from './api'
import CoachPage from './pages/CoachPage'
import PlanPage from './pages/PlanPage'
import ProgressPage from './pages/ProgressPage'
import RacesPage from './pages/RacesPage'
import SettingsPage from './pages/SettingsPage'
import TodayPage from './pages/TodayPage'
import { Banner, Icon, type IconName } from './ui'

export type Tab = 'hoy' | 'plan' | 'carreras' | 'progreso' | 'coach' | 'ajustes'
const TABS: [Tab, string, IconName][] = [
  ['hoy', 'Hoy', 'home'],
  ['plan', 'Plan', 'calendar'],
  ['carreras', 'Carreras', 'flag'],
  ['progreso', 'Progreso', 'trophy'],
  ['coach', 'Coach', 'message'],
  ['ajustes', 'Ajustes', 'settings'],
]
const TITLES: Record<Tab, string> = { hoy: 'Hoy', plan: 'Plan', carreras: 'Carreras', progreso: 'Progreso', coach: 'Coach IA', ajustes: 'Ajustes' }

const readHash = (): Tab => {
  const h = window.location.hash.slice(1) as Tab
  return TABS.some(([k]) => k === h) ? h : 'hoy'
}

type GStatus = { connected: boolean; name?: string; last_sync?: string | null }

function ago(isoTs?: string | null) {
  if (!isoTs) return 'nunca'
  const m = Math.round((Date.now() - new Date(isoTs).getTime()) / 60000)
  return m < 1 ? 'ahora' : m < 60 ? `hace ${m} min` : m < 1440 ? `hace ${Math.round(m / 60)} h` : `hace ${Math.round(m / 1440)} d`
}

function SyncChip({ st, onSynced }: { st: GStatus | null; onSynced: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (!st) return null
  if (!st.connected) return <a className="chip chip-warn" href="#ajustes"><Icon name="watch" size={14} />Conectar Garmin</a>
  return (
    <button className="btn btn-sm btn-ghost" disabled={busy} title={err ?? 'Sincronizar con Garmin'} aria-label="Sincronizar con Garmin"
      onClick={async () => {
        setBusy(true)
        setErr(null)
        try { await api.post('/api/garmin/sync?days=14'); onSynced() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
      }}>
      <Icon name="refresh" size={16} className={busy ? 'spin' : ''} />
      <span className="small">{busy ? 'Sincronizando…' : err ? 'Error al sincronizar' : `Sync ${ago(st.last_sync)}`}</span>
    </button>
  )
}

function PinScreen({ onOk }: { onOk: () => void }) {
  const [pin, setPin] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <div style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <form className="card" style={{ width: 'min(360px, 100%)', textAlign: 'center' }} onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        setErr(null)
        try { await api.post('/api/auth', { pin }); onOk() } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
      }}>
        <img src="/icon.svg" width={56} height={56} alt="" style={{ borderRadius: 14 }} />
        <h2 style={{ marginTop: 12 }}>OpenRun</h2>
        <p className="small muted">Introduce el PIN configurado en tu ordenador (OPENRUN_PIN).</p>
        <label className="sr-only" htmlFor="pin">PIN</label>
        <input id="pin" type="password" inputMode="numeric" autoComplete="current-password" value={pin} onChange={(e) => setPin(e.target.value)} autoFocus
          style={{ textAlign: 'center', fontSize: 22, letterSpacing: 6 }} />
        <button className="btn btn-primary btn-block" style={{ marginTop: 12 }} disabled={busy || !pin}>Entrar</button>
        {err && <div style={{ marginTop: 10 }}><Banner tone="bad">{err}</Banner></div>}
      </form>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState<Tab>(readHash)
  const [plan, setPlan] = useState<Plan | null | undefined>(undefined)
  const [err, setErr] = useState<string | null>(null)
  const [gst, setGst] = useState<GStatus | null>(null)
  const [tick, setTick] = useState(0) // bumps after sync so pages refetch
  const [needPin, setNeedPin] = useState(false)
  useEffect(() => {
    const on = () => setNeedPin(true)
    window.addEventListener('openrun:auth', on)
    return () => window.removeEventListener('openrun:auth', on)
  }, [])

  const reload = useCallback(() => {
    api.get<Plan | null>('/api/plan').then((p) => { setPlan(p); setErr(null) }).catch((e) => setErr(e.message))
  }, [])
  const loadStatus = useCallback(() => { api.get<GStatus>('/api/garmin/status').then(setGst).catch(() => {}) }, [])
  useEffect(() => { reload(); loadStatus() }, [reload, loadStatus])
  useEffect(() => {
    // the daily routine syncs in the background: keep the sync chip fresh
    const id = window.setInterval(loadStatus, 5 * 60000)
    const onVis = () => { if (document.visibilityState === 'visible') loadStatus() }
    document.addEventListener('visibilitychange', onVis)
    return () => { window.clearInterval(id); document.removeEventListener('visibilitychange', onVis) }
  }, [loadStatus])
  useEffect(() => {
    const on = () => setTab(readHash())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const go = (t: string) => { window.location.hash = t }
  const synced = () => { reload(); loadStatus(); setTick((x) => x + 1) }

  if (needPin) return <PinScreen onOk={() => { setNeedPin(false); synced() }} />
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Principal">
        <div className="brand"><img src="/icon.svg" width={28} height={28} alt="" style={{ borderRadius: 8 }} />OpenRun</div>
        {TABS.map(([k, l, ic]) => (
          <a key={k} href={`#${k}`} className="navitem" aria-current={tab === k ? 'page' : undefined} style={{ textDecoration: 'none' }}>
            <Icon name={ic} />{l}
          </a>
        ))}
        <div className="sidebar-foot small muted">Open source · datos en tu equipo</div>
      </nav>
      <div className="content">
        <header className="topbar">
          <h1>{TITLES[tab]}</h1>
          <div className="row">
            <SyncChip st={gst} onSynced={synced} />
            <a href="#ajustes" className="btn btn-ghost btn-icon mobile-only" aria-label="Ajustes"><Icon name="user" /></a>
          </div>
        </header>
        <main className="main" key={tick}>
          {err && !needPin && <Banner tone="bad">No se puede conectar con el servidor de OpenRun: {err}</Banner>}
          {tab === 'hoy' && <TodayPage plan={plan} reload={reload} go={go} />}
          {tab === 'plan' && <PlanPage plan={plan} reload={reload} />}
          {tab === 'carreras' && <RacesPage plan={plan ?? null} reload={reload} />}
          {tab === 'progreso' && <ProgressPage />}
          {tab === 'coach' && <CoachPage onChange={reload} />}
          {tab === 'ajustes' && <SettingsPage onChange={synced} />}
        </main>
      </div>
      <nav className="bottombar" aria-label="Principal">
        {TABS.filter(([k]) => k !== 'ajustes').map(([k, l, ic]) => (
          <button key={k} className="tabbtn" aria-current={tab === k ? 'page' : undefined} onClick={() => go(k)}>
            <Icon name={ic} size={24} />{l}
          </button>
        ))}
      </nav>
    </div>
  )
}
