import { useState } from 'react'
import { fmtPace, ZONE_LABEL, zoneLevel, zoneVar, type Step } from '../api'

export const KIND: Record<string, string> = {
  warmup: 'Calentamiento', run: 'Trabajo', recovery: 'Recuperación', rest: 'Descanso', cooldown: 'Vuelta a la calma',
}
const HEIGHT = [0.2, 0.3, 0.45, 0.6, 0.75, 0.9, 1]

export type Segment = { sec: number; level: number; kind: string; zone?: string | null; pace?: string; path: string; group?: number }

function stepSeconds(s: Step): number {
  if (s.duration_type === 'time') return s.duration_value
  if (s.duration_type === 'distance') {
    const pace = s.pace_slow && s.pace_fast ? (s.pace_slow + s.pace_fast) / 2 : 360
    return (s.duration_value / 1000) * pace
  }
  return 60
}

/** Flatten repeats into time-proportional segments. `path` identifies the source step ("2.1" = repeat 2, child 1). */
export function flatten(steps: Step[], prefix = '', group?: number): Segment[] {
  const out: Segment[] = []
  steps.forEach((s, i) => {
    const path = prefix + i
    if (s.kind === 'repeat') {
      for (let r = 0; r < (s.repeat ?? 1); r++) out.push(...flatten(s.steps ?? [], `${path}.`, i))
      return
    }
    const level = s.kind === 'rest' ? 0 : s.zone ? zoneLevel(s.zone) : s.kind === 'recovery' ? 1 : 2
    out.push({
      sec: stepSeconds(s), level, kind: s.kind, zone: s.zone, path, group,
      pace: s.pace_slow && s.pace_fast ? `${fmtPace(s.pace_slow)}–${fmtPace(s.pace_fast)}/km` : undefined,
    })
  })
  return out
}

export function zoneMinutes(segs: Segment[]) {
  const m = new Map<number, number>()
  for (const s of segs) m.set(s.level, (m.get(s.level) ?? 0) + s.sec / 60)
  return [...m.entries()].sort((a, b) => b[0] - a[0])
}

export default function StepProfile({ steps, height = 72, legend = true, onHover }: {
  steps: Step[]; height?: number; legend?: boolean; onHover?: (path: string | null) => void
}) {
  const [tip, setTip] = useState<{ x: number; text: string } | null>(null)
  const segs = flatten(steps)
  const total = segs.reduce((a, s) => a + s.sec, 0)
  if (!total) return null
  const W = 1000, gap = segs.length > 40 ? 0.6 : 1.5
  let x = 0
  const totalMin = Math.round(total / 60)
  const label = `Perfil del entreno: ${totalMin} minutos. ` + zoneMinutes(segs).map(([l, m]) => `Z${l} ${Math.round(m)} min`).join(', ')
  return (
    <div style={{ position: 'relative' }}>
      <svg className="profile" viewBox={`0 0 ${W} 100`} preserveAspectRatio="none" style={{ height }} role="img" aria-label={label}
        onMouseLeave={() => { setTip(null); onHover?.(null) }}>
        {segs.map((s, i) => {
          const w = (s.sec / total) * W
          const h = HEIGHT[s.level] * 100
          const r = (
            <rect key={i} x={x + gap / 2} y={100 - h} width={Math.max(w - gap, 0.8)} height={h} rx={2}
              fill={zoneVar(s.level)} opacity={s.kind === 'warmup' || s.kind === 'cooldown' ? 0.7 : 1}
              onMouseEnter={() => {
                setTip({ x: ((x + w / 2) / W) * 100, text: `${KIND[s.kind] ?? s.kind} ${Math.round(s.sec / 60) || '<1'}′${s.pace ? ` · ${s.pace}` : ''}${s.zone ? ` · ${ZONE_LABEL[s.zone] ?? s.zone}` : ''}` })
                onHover?.(s.path)
              }} />
          )
          x += w
          return r
        })}
      </svg>
      {tip && <div className="tooltip" style={{ left: `${tip.x}%`, top: 0 }}>{tip.text}</div>}
      {legend && (
        <div className="profile-legend">
          <span><b style={{ color: 'var(--text)' }}>{totalMin >= 60 ? `${Math.floor(totalMin / 60)} h ${totalMin % 60}′` : `${totalMin}′`}</b> total</span>
          {zoneMinutes(segs).map(([l, m]) => (
            <span key={l}><i style={{ background: zoneVar(l) }} />Z{l} {Math.round(m)}′</span>
          ))}
        </div>
      )}
    </div>
  )
}
