import { useCallback, useEffect, useState } from 'react'
import { api, type Plan } from './api'
import CoachPage from './pages/CoachPage'
import PlanPage from './pages/PlanPage'
import ProgressPage from './pages/ProgressPage'
import RacesPage from './pages/RacesPage'
import SettingsPage from './pages/SettingsPage'
import TodayPage from './pages/TodayPage'
import Onboarding, { type OnbState } from './components/Onboarding'
import { DONATE_URL, REPO_URL } from './project'
import { Banner, Icon, type IconName } from './ui'
import { getLang, LANGS, setLang, t, type Lang } from './i18n'

export type Tab = 'hoy' | 'plan' | 'carreras' | 'progreso' | 'coach' | 'ajustes'
const TABS: [Tab, string, IconName][] = [
  ['hoy', t('Today'), 'home'],
  ['plan', t('Plan'), 'calendar'],
  ['carreras', t('Races'), 'flag'],
  ['progreso', t('Progress'), 'trophy'],
  ['coach', t('Coach'), 'message'],
  ['ajustes', t('Settings'), 'settings'],
]
const TITLES: Record<Tab, string> = { hoy: t('Today'), plan: t('Plan'), carreras: t('Races'), progreso: t('Progress'), coach: t('AI coach'), ajustes: t('Settings') }

const readHash = (): Tab => {
  const h = window.location.hash.slice(1).split('/')[0] as Tab
  return TABS.some(([k]) => k === h) ? h : 'hoy'
}

type GStatus = { connected: boolean; name?: string; last_sync?: string | null }

function ago(isoTs?: string | null) {
  if (!isoTs) return t('never')
  const m = Math.round((Date.now() - new Date(isoTs).getTime()) / 60000)
  return m < 1 ? t('now') : m < 60 ? t('{n} min ago', { n: m }) : m < 1440 ? t('{n} h ago', { n: Math.round(m / 60) }) : t('{n} d ago', { n: Math.round(m / 1440) })
}

function SyncChip({ st, onSynced }: { st: GStatus | null; onSynced: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (!st) return null
  if (!st.connected) return <a className="chip chip-warn" href="#ajustes"><Icon name="watch" size={14} />{t('Connect Garmin')}</a>
  return (
    <button className="btn btn-sm btn-ghost" disabled={busy} title={err ?? t('Sync with Garmin')} aria-label={t('Sync with Garmin')}
      onClick={async () => {
        setBusy(true)
        setErr(null)
        try { await api.post('/api/garmin/sync?days=14'); onSynced() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
      }}>
      <Icon name="refresh" size={16} className={busy ? 'spin' : ''} />
      <span className="small">{busy ? t('Syncing…') : err ? t('Sync failed') : `Sync ${ago(st.last_sync)}`}</span>
    </button>
  )
}

export type Me = { id: number; username: string; name: string; is_admin: boolean; lang?: Lang | null }

const inviteFromHash = () => {
  const m = window.location.hash.match(/^#invitacion=([\w-]+)/)
  return m ? m[1] : null
}

function AuthScreen({ onOk }: { onOk: () => void }) {
  const [code, setCode] = useState<string | null>(inviteFromHash)
  const [username, setUsername] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [invite, setInvite] = useState<{ ok: boolean; note?: string } | null>(null)
  useEffect(() => {
    if (!code) return
    api.get<{ ok: boolean; note?: string }>(`/api/auth/invite/${code}`).then(setInvite).catch((e) => setErr((e as Error).message))
  }, [code])
  const register = !!code
  return (
    <div style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <form className="card stack" style={{ width: 'min(380px, 100%)', textAlign: 'center' }} onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        setErr(null)
        try {
          if (register) await api.post('/api/auth/register', { code, username, name, password })
          else await api.post('/api/auth', { username, password })
          if (register) window.location.hash = 'ajustes'
          onOk()
        } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
      }}>
        <div>
          <img src="/icon.svg" width={56} height={56} alt="" style={{ borderRadius: 14 }} />
          <h2 style={{ marginTop: 12 }}>OpenRun</h2>
          <p className="small muted">{register ? t('Create your account. Your data, your plan and your Garmin are yours alone.') : t('Sign in to see your plan.')}</p>
          {register && invite === null && !err && <p className="small muted">{t('Checking invitation…')}</p>}
        </div>
        <label className="field" style={{ textAlign: 'left' }}>{t('Username')}
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" autoFocus required />
        </label>
        {register && (
          <label className="field" style={{ textAlign: 'left' }}>{t('Name')}
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </label>
        )}
        <label className="field" style={{ textAlign: 'left' }}>{t('Password')}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 10 : undefined} required />
        </label>
        {register && <p className="small muted" style={{ textAlign: 'left', margin: 0 }}>{t('At least 10 characters. A phrase of several words is easy to remember and secure.')}</p>}
        <button className="btn btn-primary btn-block" disabled={busy || !username || !password}>{register ? t('Create account') : t('Sign in')}</button>
        {err && <Banner tone="bad">{err}</Banner>}
        {register
          ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setCode(null); window.location.hash = '' }}>{t('I already have an account')}</button>
          : <p className="small muted" style={{ margin: 0 }}>{t('No account? Ask whoever runs this app for an invitation.')}</p>}
        <div className="row small" style={{ justifyContent: 'center', gap: 4 }}>
          {LANGS.map(([code, label]) => (
            <button key={code} type="button" className="btn btn-ghost btn-sm" aria-pressed={code === getLang()} onClick={() => setLang(code)}>{label}</button>
          ))}
        </div>
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
  const [needPin, setNeedPin] = useState(() => !!inviteFromHash())
  const [me, setMe] = useState<Me | null>(null)
  const [onb, setOnb] = useState<OnbState | null>(null)
  const loadMe = useCallback(() => {
    api.get<{ authed: boolean; user: Me | null }>('/api/auth').then((r) => {
      setMe(r.user)
      if (!r.authed) setNeedPin(true)
      // the account's language wins (same on every device); a new account takes this browser's
      if (r.user?.lang && r.user.lang !== getLang()) setLang(r.user.lang)
      else if (r.user && !r.user.lang) api.put('/api/account', { lang: getLang() }).catch(() => {})
    }).catch(() => {})
  }, [])
  useEffect(() => { loadMe() }, [loadMe])
  useEffect(() => { if (me) api.get<OnbState>('/api/onboarding').then(setOnb).catch(() => {}) }, [me])
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

  if (needPin) return <AuthScreen onOk={() => { setNeedPin(false); loadMe(); synced() }} />
  return (
    <div className="shell">
      <nav className="sidebar" aria-label={t('Main')}>
        <div className="brand"><img src="/icon.svg" width={28} height={28} alt="" style={{ borderRadius: 8 }} />OpenRun</div>
        {TABS.map(([k, l, ic]) => (
          <a key={k} href={`#${k}`} className="navitem" aria-current={tab === k ? 'page' : undefined} style={{ textDecoration: 'none' }}>
            <Icon name={ic} />{l}
          </a>
        ))}
        <div className="sidebar-foot small muted">
          {me ? <a href="#ajustes" style={{ color: 'inherit' }}>{me.name || me.username}</a> : 'OpenRun'} · <a href={REPO_URL} target="_blank" rel="noreferrer" style={{ color: 'inherit' }}>open source</a>
          <div style={{ marginTop: 6 }}><a href={DONATE_URL} target="_blank" rel="noreferrer" style={{ color: 'inherit' }}>♥ {t('Support OpenRun')}</a></div>
        </div>
      </nav>
      <div className="content">
        <header className="topbar">
          <h1>{TITLES[tab]}</h1>
          <div className="row">
            <SyncChip st={gst} onSynced={synced} />
            <a href="#ajustes" className="btn btn-ghost btn-icon mobile-only" aria-label={t('Settings')}><Icon name="user" /></a>
          </div>
        </header>
        <main className="main" key={tick}>
          {err && !needPin && <Banner tone="bad">{t('Cannot reach the OpenRun server: {err}', { err })}</Banner>}
          {tab === 'hoy' && (onb?.needed && plan === null
            ? <Onboarding name={me?.name || ''} onFinish={() => { setOnb({ ...onb, needed: false, done: true }); reload() }} />
            : <TodayPage plan={plan} reload={reload} go={go} />)}
          {tab === 'plan' && <PlanPage plan={plan} reload={reload} />}
          {tab === 'carreras' && <RacesPage plan={plan ?? null} reload={reload} />}
          {tab === 'progreso' && <ProgressPage />}
          {tab === 'coach' && <CoachPage onChange={reload} />}
          {tab === 'ajustes' && <SettingsPage onChange={synced} me={me} onMe={loadMe} />}
        </main>
      </div>
      <nav className="bottombar" aria-label={t('Main')}>
        {TABS.filter(([k]) => k !== 'ajustes').map(([k, l, ic]) => (
          <button key={k} className="tabbtn" aria-current={tab === k ? 'page' : undefined} onClick={() => go(k)}>
            <Icon name={ic} size={24} />{l}
          </button>
        ))}
      </nav>
    </div>
  )
}
