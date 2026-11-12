import { useCallback, useEffect, useState } from 'react'
import { api, type Plan } from './api'
import CoachPage from './pages/CoachPage'
import ActivitiesPage from './pages/ActivitiesPage'
import PlanPage from './pages/PlanPage'
import ProgressPage from './pages/ProgressPage'
import RacesPage from './pages/RacesPage'
import SettingsPage from './pages/SettingsPage'
import TodayPage from './pages/TodayPage'
import Onboarding, { type OnbState } from './components/Onboarding'
import PrivacySheet from './components/Privacy'
import Tour from './components/Tour'
import { REPO_URL } from './project'
import { Banner, Icon, type IconName } from './ui'
import { getLang, LANGS, setLang, t, type Lang } from './i18n'

export type Tab = 'hoy' | 'plan' | 'actividades' | 'carreras' | 'progreso' | 'coach' | 'ajustes'
const TABS: [Tab, string, IconName][] = [
  ['hoy', t('Today'), 'home'],
  ['plan', t('Plan'), 'calendar'],
  ['actividades', t('Activities'), 'activity'],
  ['carreras', t('Races'), 'flag'],
  ['progreso', t('Progress'), 'trophy'],
  ['coach', t('Coach'), 'message'],
  ['ajustes', t('Settings'), 'settings'],
]
const TITLES: Record<Tab, string> = { hoy: t('Today'), plan: t('Plan'), actividades: t('Activities'), carreras: t('Races'), progreso: t('Progress'), coach: t('AI coach'), ajustes: t('Settings') }

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

export type Me = { id: number; username: string; name: string; is_admin: boolean; lang?: Lang | null; is_demo?: boolean }

const inviteFromHash = () => {
  const m = window.location.hash.match(/^#invitacion=([\w-]+)/)
  return m ? m[1] : null
}
const resetFromHash = () => {
  const m = window.location.hash.match(/^#restablecer=([\w-]+)/)
  return m ? m[1] : null
}

function AuthScreen({ onOk }: { onOk: () => void }) {
  const [code, setCode] = useState<string | null>(inviteFromHash)
  const [resetCode, setResetCode] = useState<string | null>(resetFromHash)
  const [username, setUsername] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [privacy, setPrivacy] = useState(false)
  const [showPrivacy, setShowPrivacy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [forgot, setForgot] = useState(false)
  const [invite, setInvite] = useState<{ ok: boolean; note?: string } | null>(null)
  const [resetFor, setResetFor] = useState<{ username: string; name: string } | null>(null)
  useEffect(() => {
    if (!code) return
    api.get<{ ok: boolean; note?: string }>(`/api/auth/invite/${code}`).then((r) => { setInvite(r); if (r.note) setName((n) => n || r.note || '') }).catch((e) => setErr((e as Error).message))
  }, [code])
  useEffect(() => {
    if (!resetCode) return
    api.get<{ username: string; name: string }>(`/api/auth/reset/${resetCode}`).then((r) => { setResetFor(r); setUsername(r.username) })
      .catch((e) => setErr((e as Error).message))
  }, [resetCode])
  const mode: 'login' | 'register' | 'reset' = resetCode ? 'reset' : code ? 'register' : 'login'
  const [demo, setDemo] = useState(false)
  useEffect(() => { api.get<{ demo?: boolean }>('/api/auth').then((r) => setDemo(!!r.demo)).catch(() => {}) }, [])
  const toLogin = () => { setCode(null); setResetCode(null); setErr(null); window.location.hash = '' }
  const intro = mode === 'register' ? t('Create your account. Your data, your plan and your Garmin are yours alone.')
    : mode === 'reset' ? (resetFor ? t('Hi {name}, choose a new password.', { name: resetFor.name || resetFor.username }) : t('Checking link…'))
      : t('Sign in to see your plan.')
  const newPw = mode !== 'login'
  return (
    <div style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <form className="card stack" style={{ width: 'min(380px, 100%)', textAlign: 'center' }} onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        setErr(null)
        try {
          if (mode === 'register') await api.post('/api/auth/register', { code, username, name, password, privacy })
          else if (mode === 'reset') await api.post('/api/auth/reset', { code: resetCode, password })
          else await api.post('/api/auth', { username, password })
          if (newPw) window.location.hash = 'hoy'
          onOk()
        } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
      }}>
        <div>
          <img src="/icon.svg" width={56} height={56} alt="" style={{ borderRadius: 14 }} />
          <h2 style={{ marginTop: 12 }}>OpenRun</h2>
          <p className="small muted">{intro}</p>
          {mode === 'register' && invite === null && !err && <p className="small muted">{t('Checking invitation…')}</p>}
        </div>
        <label className="field" style={{ textAlign: 'left' }}>{t('Username')}
          <input value={username} onChange={(e) => setUsername(e.target.value.toLowerCase())} autoComplete="username" autoCapitalize="none"
            autoCorrect="off" spellCheck={false} autoFocus={mode !== 'reset'} readOnly={mode === 'reset'} required />
        </label>
        {mode === 'register' && <p className="small muted" style={{ textAlign: 'left', margin: '-6px 0 0' }}>{t('Lowercase letters and numbers, no spaces. For example: ana.garcia')}</p>}
        {mode === 'register' && (
          <label className="field" style={{ textAlign: 'left' }}>{t('Name')}
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" placeholder={t('How the coach will call you')} />
          </label>
        )}
        <label className="field" style={{ textAlign: 'left' }}>{mode === 'reset' ? t('New password') : t('Password')}
          <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
            <input type={showPw ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} style={{ flex: 1, minWidth: 0 }}
              autoComplete={newPw ? 'new-password' : 'current-password'} minLength={newPw ? 10 : undefined} autoFocus={mode === 'reset'} required />
            <button type="button" className="btn btn-ghost btn-icon" aria-label={showPw ? t('Hide password') : t('Show password')}
              aria-pressed={showPw} onClick={() => setShowPw(!showPw)}><Icon name={showPw ? 'eyeOff' : 'eye'} size={18} /></button>
          </div>
        </label>
        {newPw && (
          <p className="small muted" style={{ textAlign: 'left', margin: 0 }}>
            {t('At least 10 characters. A phrase of several words is easy to remember and secure.')}
            {password && password.length < 10 && <> <b>{t('{n} more', { n: 10 - password.length })}</b></>}
          </p>
        )}
        {mode === 'register' && (
          <label className="row small" style={{ textAlign: 'left', gap: 8, flexWrap: 'nowrap', alignItems: 'flex-start', cursor: 'pointer' }}>
            <input type="checkbox" checked={privacy} onChange={(e) => setPrivacy(e.target.checked)} style={{ marginTop: 3 }} required />
            <span>{t('I have read the')} <button type="button" className="linkbtn" onClick={() => setShowPrivacy(true)}>{t('privacy notice')}</button></span>
          </label>
        )}
        <button className="btn btn-primary btn-block" disabled={busy || !username || !password || (mode === 'register' && !privacy) || (mode === 'reset' && !resetFor)}>
          {mode === 'register' ? t('Create account') : mode === 'reset' ? t('Save and sign in') : t('Sign in')}
        </button>
        {err && <Banner tone="bad">{err}</Banner>}
        {mode !== 'login'
          ? <button type="button" className="btn btn-ghost btn-sm" onClick={toLogin}>{t('I already have an account')}</button>
          : <>
            <button type="button" className="btn btn-ghost btn-sm" aria-expanded={forgot} onClick={() => setForgot(!forgot)}>{t('Forgot your password?')}</button>
            {forgot && <p className="small muted" style={{ margin: 0 }}>{t('Ask whoever runs this app: they can send you a link to choose a new one.')}</p>}
            <p className="small muted" style={{ margin: 0 }}>{t('No account? Ask whoever runs this app for an invitation.')}</p>
          </>}
        {mode === 'login' && demo && (
          <button type="button" className="btn btn-block" disabled={busy} onClick={async () => {
            setBusy(true)
            try { await api.post('/api/auth/demo'); onOk() } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
          }}><Icon name="sparkles" />{t('Try the demo')}</button>
        )}
        <div className="row small" style={{ justifyContent: 'center', gap: 4 }}>
          {LANGS.map(([code, label]) => (
            <button key={code} type="button" className="btn btn-ghost btn-sm" aria-pressed={code === getLang()} onClick={() => setLang(code)}>{label}</button>
          ))}
        </div>
      </form>
      {showPrivacy && <PrivacySheet onClose={() => setShowPrivacy(false)} />}
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState<Tab>(readHash)
  const [plan, setPlan] = useState<Plan | null | undefined>(undefined)
  const [err, setErr] = useState<string | null>(null)
  const [gst, setGst] = useState<GStatus | null>(null)
  const [tick, setTick] = useState(0) // bumps after sync so pages refetch
  const [needPin, setNeedPin] = useState(() => !!inviteFromHash() || !!resetFromHash())
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
  // one-minute tour: once per account (after the welcome steps), and again from Settings
  const [tour, setTour] = useState(false)
  useEffect(() => {
    if (!me || !onb || onb.needed) return
    const key = `openrun.tour.${me.id}`
    let seen = false
    try { seen = localStorage.getItem(key) === '1' } catch { /* private mode */ }
    if (seen) return
    api.get<{ tour_seen?: boolean }>('/api/settings').then((st) => { if (!st.tour_seen) setTour(true) }).catch(() => {})
  }, [me, onb])
  useEffect(() => {
    const on = () => setTour(true)
    window.addEventListener('openrun:tour', on)
    return () => window.removeEventListener('openrun:tour', on)
  }, [])
  const closeTour = useCallback(() => {
    setTour(false)
    if (!me) return
    try { localStorage.setItem(`openrun.tour.${me.id}`, '1') } catch { /* private mode */ }
    api.put('/api/settings', { tour_seen: true }).catch(() => {})
  }, [me])
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
        </div>
      </nav>
      <div className="content">
        <header className="topbar">
          <h1>{TITLES[tab]}</h1>
          <div className="row">
            {!me?.is_demo && <SyncChip st={gst} onSynced={synced} />}
            <a href="#coach" className="btn btn-ghost btn-icon mobile-only" aria-label={t('AI coach')}><Icon name="message" /></a>
            <a href="#ajustes" className="btn btn-ghost btn-icon mobile-only" aria-label={t('Settings')}><Icon name="user" /></a>
          </div>
        </header>
        <main className="main" key={tick}>
          {me?.is_demo && <Banner tone="info">{t('Demo account with sample data. Garmin, the AI coach and account changes are off; anything you change is reset every day.')}</Banner>}
          {err && !needPin && <Banner tone="bad">{t('Cannot reach the OpenRun server: {err}', { err })}</Banner>}
          {tab === 'hoy' && (onb?.needed && plan === null
            ? <Onboarding name={me?.name || ''} onFinish={() => { setOnb({ ...onb, needed: false, done: true }); reload() }} />
            : <TodayPage plan={plan} reload={reload} go={go} />)}
          {tab === 'plan' && <PlanPage plan={plan} reload={reload} />}
          {tab === 'actividades' && <ActivitiesPage />}
          {tab === 'carreras' && <RacesPage plan={plan ?? null} reload={reload} />}
          {tab === 'progreso' && <ProgressPage />}
          {tab === 'coach' && <CoachPage onChange={reload} />}
          {tab === 'ajustes' && <SettingsPage onChange={synced} me={me} onMe={loadMe} />}
        </main>
      </div>
      {tour && <Tour onClose={closeTour} />}
      <nav className="bottombar" aria-label={t('Main')}>
        {TABS.filter(([k]) => k !== 'ajustes' && k !== 'coach').map(([k, l, ic]) => (
          <button key={k} className="tabbtn" aria-current={tab === k ? 'page' : undefined} onClick={() => go(k)}>
            <Icon name={ic} size={24} />{l}
          </button>
        ))}
      </nav>
    </div>
  )
}
