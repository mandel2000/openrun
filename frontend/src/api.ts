import { useCallback, useEffect, useState } from 'react'

export type Step = {
  kind: 'warmup' | 'run' | 'recovery' | 'rest' | 'cooldown' | 'repeat'
  duration_type: 'distance' | 'time' | 'open'
  duration_value: number
  zone?: string | null
  pace_slow?: number | null
  pace_fast?: number | null
  hr_low?: number | null
  hr_high?: number | null
  repeat?: number
  steps?: Step[]
  note?: string
}

export type Workout = {
  id: number
  date: string
  week: number
  status: 'planned' | 'done' | 'skipped' | 'modified'
  activity_id?: number | null
  extra?: boolean
  race_id?: number
  garmin_workout_id?: string | null
  note?: string | null
  type: string
  title: string
  description: string
  steps: Step[]
  intensity: 'rest' | 'low' | 'moderate' | 'high'
  phase: string
  distance_km: number
  duration_min: number
  sport: 'running' | 'strength'
  exercises?: { name: string; sets: number; reps: string; rest_s: number; cue: string; load?: string }[]
}

export type PlanWeek = {
  index: number
  start: string
  end: string
  done_km: number
  phase: string
  target_km: number
  planned_km: number
  vdot: number
  is_recovery: boolean
  low_intensity_pct: number
  workouts: Workout[]
}

export type PaceRange = { slow: number; fast: number; slow_fmt: string; fast_fmt: string }
export type Prediction = { seconds: number; time: string; pace: string }

export type Plan = {
  id: number
  name: string
  goal: string
  start_date: string
  race_date: string | null
  goal_time: string | null
  vdot_start: number
  vdot_goal: number | null
  paces_start: Record<string, PaceRange | number>
  predictions_start: Record<string, Prediction>
  predictions_end: Record<string, Prediction>
  warnings: string[]
  weeks: PlanWeek[]
}

export type Readiness = {
  status: 'green' | 'amber' | 'red' | 'unknown'
  reasons: string[]
  hrv_7d: number | null
  hrv_baseline: number | null
  swc_low: number | null
  swc_high: number | null
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  const r = await fetch(url, init)
  if (r.status === 401 && !url.startsWith('/api/auth')) window.dispatchEvent(new Event('openrun:auth'))
  if (!r.ok) {
    let msg = r.statusText
    try {
      msg = (await r.json()).detail ?? msg
    } catch {
      /* not json */
    }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return r.json() as Promise<T>
}

export const api = {
  get: <T,>(u: string) => req<T>('GET', u),
  post: <T,>(u: string, b?: unknown) => req<T>('POST', u, b ?? {}),
  put: <T,>(u: string, b?: unknown) => req<T>('PUT', u, b),
  del: <T,>(u: string) => req<T>('DELETE', u),
}

export const fmtPace = (s?: number | null) => {
  if (!s) return ''
  const r = Math.round(s)
  return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, '0')}`
}

export const ZONE_LABEL: Record<string, string> = {
  recovery: 'Regenerativo', easy: 'Suave', long: 'Largo', marathon: 'Maratón', half: 'Medio',
  threshold: 'Umbral', ten_k: '10K', five_k: '5K', interval: 'Intervalos (I)', repetition: 'Repeticiones (R)',
}

export const iso = (d: Date) => {
  const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
  return z.toISOString().slice(0, 10)
}

export const DAY_NAMES = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

export const PHASE_LABEL: Record<string, string> = { base: 'Base', build: 'Desarrollo', peak: 'Específico', taper: 'Afinamiento', race: 'Carrera' }
export const STATUS_LABEL: Record<string, string> = { planned: 'Planificado', done: 'Hecho', skipped: 'No realizado', modified: 'Ajustado' }
export const DIST_LABEL: Record<string, string> = { '1k': '1K', mile: 'Milla', '5k': '5K', '10k': '10K', half: 'Media maratón', marathon: 'Maratón' }

// Intensity zone tokens (index 0..6) per pace zone / workout type
const ZONE_LEVEL: Record<string, number> = {
  recovery: 1, easy: 2, long: 2, marathon: 3, half: 3, threshold: 4, ten_k: 4, five_k: 5, interval: 5, repetition: 6,
}
export const zoneLevel = (zone?: string | null) => (zone ? ZONE_LEVEL[zone] ?? 2 : 0)
export const zoneVar = (lvl: number) => `var(--z${lvl})`
const TYPE_LEVEL: Record<string, number> = {
  recovery: 1, easy: 2, long: 2, strides: 2, shakeout: 1, progression: 3, hills: 5, tempo: 4, threshold: 4, cruise: 4,
  vo2max: 5, intervals: 5, reps: 6, repetition: 6, race_pace: 4, race: 5, strength: 0,
}
export const workoutLevel = (w: Pick<Workout, 'type' | 'intensity' | 'sport'>) =>
  w.sport === 'strength' ? 0 : TYPE_LEVEL[w.type] ?? ({ low: 2, moderate: 4, high: 5, rest: 0 }[w.intensity] ?? 2)

export const fmtDate = (d: string, o: Intl.DateTimeFormatOptions = { weekday: 'short', day: 'numeric', month: 'short' }) =>
  new Date(d + 'T12:00').toLocaleDateString('es-ES', o)
export const fmtDur = (min: number) => {
  const m = Math.round(min)
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}′` : `${m}′`
}
export const daysBetween = (a: string, b: string) => Math.round((new Date(b + 'T12:00').getTime() - new Date(a + 'T12:00').getTime()) / 86400000)
export const addDays = (d: string, n: number) => iso(new Date(new Date(d + 'T12:00').getTime() + n * 86400000))
export const garminActivityUrl = (externalId?: string | null) =>
  externalId?.startsWith('garmin:') ? `https://connect.garmin.com/modern/activity/${externalId.slice(7)}` : null

export function useApi<T>(url: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(!!url)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => {
    if (!url) return
    setLoading(true)
    api.get<T>(url).then((d) => { setData(d); setError(null) }).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [url])
  useEffect(reload, [reload])
  return { data, loading, error, reload, setData }
}

export type Race = {
  id: number; name: string; date: string; distance_m: number | null; priority: 'A' | 'B' | 'C'; location: string | null
  url: string | null; source: string; external_id: string | null; goal_time_s: number | null; result_time_s: number | null
  notes: string | null; days_to_go: number; has_course?: boolean; strategy_target_s?: number | null
}
export const fmtTime = (s?: number | null) => {
  if (!s) return '–'
  const r = Math.round(s), h = Math.floor(r / 3600), m = Math.floor((r % 3600) / 60), sec = r % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}
export const fmtKm = (m?: number | null) => (m ? `${+(m / 1000).toFixed(m % 1000 ? 1 : 0)} km` : '')

export type LapRow = {
  i: number; type: string; step: number | null; distance_m: number; duration_s: number; pace: number | null
  avg_hr: number | null; max_hr: number | null; compliance: number | null; zone: string | null; kind: string | null
  target: [number, number] | null; status: 'ok' | 'fast' | 'slow' | null; dev_pct: number | null
}
export type Analysis = {
  laps: LapRow[]; n_work: number; verdict: 'too_easy' | 'too_hard' | 'on_target' | null; notes: string[]
  on_target_pct?: number; avg_dev_pct?: number; work_hr?: number | null; planned_id: number | null; planned_title: string | null
}
export const VERDICT: Record<string, [string, string]> = {
  too_easy: ['Más fácil de lo previsto', 'chip-good'], on_target: ['En objetivo', 'chip-accent'], too_hard: ['Costó más de lo previsto', 'chip-warn'],
}
export type Weather = { available?: false; temp: number; dew: number; rh: number; hour: number; pct: number; sum_f: number; too_hot: boolean; date: string }
