import { useEffect, useState } from 'react'
import { api } from '../api'
import { PlanForm } from '../pages/PlanPage'
import { GarminCard, HistoryImportCard } from '../pages/SettingsPage'
import { Banner, Icon } from '../ui'

// First run for a new user: about you → where your runs come from → goal and plan → done.
export type OnbState = { done: boolean; needed: boolean; activities: number; garmin: boolean; profile: boolean; weekly_km: number | null; longest_km: number | null; vdot: number | null }

const STEPS = ['Sobre ti', 'Tus datos', 'Tu objetivo', 'Listo']

function AboutYou({ name, onNext }: { name: string; onNext: () => void }) {
  const [a, setA] = useState({ name, sex: 'male', age: '', weight_kg: '', max_hr: '', rest_hr: '' })
  const [err, setErr] = useState<string | null>(null)
  const set = (k: string, v: string) => setA((p) => ({ ...p, [k]: v }))
  const num = (v: string) => (v.trim() === '' ? null : +v)
  useEffect(() => {  // coming back to this step: show what was saved
    api.get<Record<string, string | number | null>>('/api/athlete').then((x) => setA((p) => ({
      ...p, sex: String(x.sex ?? p.sex),
      ...Object.fromEntries((['age', 'weight_kg', 'max_hr', 'rest_hr'] as const).filter((k) => x[k] != null).map((k) => [k, String(x[k])])),
    }))).catch(() => {})
  }, [])
  return (
    <form className="stack" onSubmit={async (e) => {
      e.preventDefault()
      setErr(null)
      try {
        await api.put('/api/athlete', { name: a.name, sex: a.sex, age: num(a.age), weight_kg: num(a.weight_kg), max_hr: num(a.max_hr), rest_hr: num(a.rest_hr) })
        onNext()
      } catch (e) { setErr((e as Error).message) }
    }}>
      <p className="text-2" style={{ margin: 0 }}>Con esto calculo tus zonas de pulso y la carga de cada entreno. Si no sabes tus pulsaciones, déjalas vacías: se estiman de tus actividades.</p>
      <div className="form-grid">
        <label className="field">Nombre<input value={a.name} onChange={(e) => set('name', e.target.value)} /></label>
        <label className="field">Sexo<select value={a.sex} onChange={(e) => set('sex', e.target.value)}><option value="male">Hombre</option><option value="female">Mujer</option></select></label>
        <label className="field">Edad<input type="number" inputMode="numeric" min={10} max={100} required value={a.age} onChange={(e) => set('age', e.target.value)} /></label>
        <label className="field">Peso (kg)<input type="number" inputMode="decimal" min={30} max={200} value={a.weight_kg} onChange={(e) => set('weight_kg', e.target.value)} /></label>
        <label className="field">FC máxima (opcional)<input type="number" inputMode="numeric" min={120} max={230} value={a.max_hr} onChange={(e) => set('max_hr', e.target.value)} /></label>
        <label className="field">FC en reposo (opcional)<input type="number" inputMode="numeric" min={30} max={100} value={a.rest_hr} onChange={(e) => set('rest_hr', e.target.value)} /></label>
      </div>
      <div className="row"><button className="btn btn-primary">Continuar<Icon name="chevronRight" size={16} /></button>{err && <span className="err small">{err}</span>}</div>
    </form>
  )
}

function YourData({ st, refresh, onNext }: { st: OnbState; refresh: () => Promise<void>; onNext: () => void }) {
  const [pick, setPick] = useState<'garmin' | 'files' | null>(st.garmin ? 'garmin' : null)
  const opts: [typeof pick, string, string][] = [
    ['garmin', 'Tengo reloj Garmin', 'Sincroniza actividades, sueño y HRV, y envía cada entreno a tu reloj.'],
    ['files', 'Otro reloj o Strava', 'Sube tu exportación de Strava (.zip) o archivos FIT/GPX/TCX. Después puedes subir cada carrera.'],
  ]
  return (
    <div className="stack">
      <p className="text-2" style={{ margin: 0 }}>Con tu historial el plan parte de tu nivel real y los ritmos se ajustan solos. Puedes hacerlo ahora o más tarde en Ajustes.</p>
      <div className="choice-grid">
        {opts.map(([k, t, d]) => (
          <button key={k} type="button" className={`choice${pick === k ? ' on' : ''}`} aria-pressed={pick === k} onClick={() => setPick(k)}>
            <Icon name={k === 'garmin' ? 'watch' : 'upload'} /><b>{t}</b><span className="small muted">{d}</span>
          </button>
        ))}
      </div>
      {pick === 'garmin' && <GarminCard onChange={refresh} />}
      {pick === 'files' && <HistoryImportCard />}
      {st.activities > 0 && <Banner tone="ok">{st.activities} actividades cargadas{st.weekly_km != null ? ` · media reciente ${st.weekly_km} km/semana` : ''}.</Banner>}
      <div className="row">
        <button className="btn btn-primary" onClick={() => refresh().then(onNext)}>{st.activities ? 'Continuar' : 'Continuar sin datos'}<Icon name="chevronRight" size={16} /></button>
      </div>
    </div>
  )
}

export default function Onboarding({ name, onFinish }: { name: string; onFinish: () => void }) {
  const [step, setStep] = useState(0)
  const [st, setSt] = useState<OnbState | null>(null)
  const refresh = () => api.get<OnbState>('/api/onboarding').then(setSt).catch(() => {})
  useEffect(() => { refresh() }, [])
  useEffect(() => {  // pick up Garmin syncs / file imports finishing while on the data step
    if (step !== 1) return
    const id = window.setInterval(refresh, 4000)
    return () => window.clearInterval(id)
  }, [step])
  const finish = () => api.post('/api/onboarding/done').then(onFinish)
  if (!st) return null
  const initial: Record<string, unknown> = {}
  if (st.weekly_km) initial.current_weekly_km = st.weekly_km
  if (st.longest_km) initial.longest_recent_run_km = st.longest_km
  return (
    <div className="stack" style={{ maxWidth: 820 }}>
      <div className="card stack">
        <div className="row spread">
          <h2 style={{ margin: 0 }}>{step === 0 ? `Hola${name ? `, ${name}` : ''} 👋` : STEPS[step]}</h2>
          {step < 3 && <button className="btn btn-ghost btn-sm" onClick={finish}>Saltar por ahora</button>}
        </div>
        <ol className="onb-steps" aria-label="Pasos">
          {STEPS.map((s, i) => <li key={s} className={i === step ? 'on' : i < step ? 'done' : ''} aria-current={i === step ? 'step' : undefined}>{i < step ? <Icon name="check" size={14} /> : i + 1} {s}</li>)}
        </ol>
        {step === 0 && <AboutYou name={name} onNext={() => setStep(1)} />}
        {step === 1 && <YourData st={st} refresh={refresh} onNext={() => setStep(2)} />}
        {step === 3 && (
          <div className="stack">
            <p style={{ margin: 0 }}>Tu plan está listo. Cada mañana la app revisa cómo llegas (sueño, pulso, tus sensaciones) y ajusta el entreno si hace falta.</p>
            <ul className="small text-2" style={{ margin: 0, paddingLeft: 18 }}>
              <li>En <b>Hoy</b> tienes el entreno del día y un check-in de dos toques.</li>
              <li>Si faltas a una sesión clave, te propongo dónde recolocarla.</li>
              <li>Activa los avisos en <a href="#ajustes">Ajustes › Notificaciones</a> (en iPhone, primero añade la app a la pantalla de inicio).</li>
              <li>El <b>Coach IA</b> responde dudas y puede cambiar tu plan.</li>
            </ul>
            <div className="row"><button className="btn btn-primary" onClick={finish}>Empezar<Icon name="chevronRight" size={16} /></button></div>
          </div>
        )}
      </div>
      {step === 2 && <PlanForm initial={initial} onCreated={() => setStep(3)} onCancel={() => setStep(1)} />}
    </div>
  )
}
