import { useEffect, useState } from 'react'
import { api } from '../api'
import { t } from '../i18n'

export type Exercise = { name: string; sets: number; reps: string; rest_s: number; cue: string; load?: string }
export type Routine = { title: string; goal: string; minutes: number; exercises: Exercise[] }

// Checklist of exercises; progress is kept per workout on this device only (it's a gym aid).
export function ExerciseList({ items, storeKey }: { items: Exercise[]; storeKey?: string }) {
  const [done, setDone] = useState<Record<number, number>>(() => {
    if (!storeKey) return {}
    try { return JSON.parse(localStorage.getItem(storeKey) || '{}') } catch { return {} }
  })
  useEffect(() => {
    if (!storeKey) return
    try { localStorage.setItem(storeKey, JSON.stringify(done)) } catch { /* private mode */ }
  }, [done, storeKey])
  return (
    <ol className="exercises">
      {items.map((e, i) => {
        const n = done[i] ?? 0
        return (
          <li key={e.name} className={n >= e.sets ? 'ex-done' : ''}>
            <div className="row spread" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0 }}>
                <b>{e.name}</b>
                <div className="small num">{e.sets > 1 ? `${e.sets} × ` : ''}{e.reps}{e.rest_s ? ` · ${t('rest')} ${e.rest_s >= 60 ? `${Math.round(e.rest_s / 6) / 10} min` : `${e.rest_s} s`}` : ''}{e.load ? ` · ${e.load}` : ''}</div>
                <div className="small muted">{e.cue}</div>
              </div>
              {storeKey && (
                <button className="btn btn-sm" style={{ flex: 'none' }} aria-label={t('Set done: {name}', { name: e.name })}
                  onClick={() => setDone((d) => ({ ...d, [i]: n >= e.sets ? 0 : n + 1 }))}>
                  {n >= e.sets ? '✓' : `${n}/${e.sets}`}
                </button>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

export function RoutineBlock({ kind }: { kind: 'warmup' | 'mobility' }) {
  const [r, setR] = useState<Routine | null>(null)
  useEffect(() => { api.get<Record<string, Routine>>('/api/routines').then((x) => setR(x[kind])).catch(() => {}) }, [kind])
  if (!r) return null
  return (
    <details className="routine">
      <summary><b>{r.title}</b> <span className="small muted">· {r.minutes} min</span></summary>
      <p className="small text-2">{r.goal}</p>
      <ExerciseList items={r.exercises} />
    </details>
  )
}
