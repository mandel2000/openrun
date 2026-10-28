import { useEffect, useState } from 'react'
import { api, fmtPace, VERDICT, ZONE_LABEL, zoneLevel, zoneVar, type Analysis, type LapRow } from '../api'
import { Banner, Icon, Segmented, Sheet, Skeleton } from '../ui'
import ActivityDetail from './ActivityDetail'

const LAP_TYPE: Record<string, string> = { WARMUP: 'Calent.', ACTIVE: 'Trabajo', REST: 'Recup.', RECOVERY: 'Recup.', COOLDOWN: 'Vuelta calma', INTERVAL: 'Trabajo' }

function StatusChip({ r }: { r: LapRow }) {
  if (!r.status) return r.compliance != null ? <span className="small muted num">{r.compliance}%</span> : null
  const [label, cls] = r.status === 'ok' ? ['OK', 'chip-good'] : r.status === 'fast' ? [`+${r.dev_pct}%`, 'chip-accent'] : [`${r.dev_pct}%`, 'chip-warn']
  return <span className={`chip ${cls}`} title={r.status === 'ok' ? 'En rango' : r.status === 'fast' ? 'Más rápido que el objetivo' : 'Más lento que el objetivo'}>{label}</span>
}

export function AnalysisSummary({ a }: { a: Analysis }) {
  const v = a.verdict ? VERDICT[a.verdict] : null
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row">
        {v && <span className={`chip ${v[1]}`}>{v[0]}</span>}
        {a.on_target_pct != null && <span className="chip num">{a.on_target_pct}% series en rango</span>}
        {a.avg_dev_pct != null && <span className="chip num">{a.avg_dev_pct > 0 ? '+' : ''}{a.avg_dev_pct}% vs objetivo</span>}
        {a.work_hr && <span className="chip num"><Icon name="heart" size={13} />{a.work_hr} ppm en series</span>}
      </div>
      {a.notes.map((n) => <div key={n} className="small text-2">{n}</div>)}
    </div>
  )
}

export function LapsTable({ laps }: { laps: LapRow[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th className="hide-sm">#</th><th>Tipo</th><th className="n">Dist.</th><th className="n">Ritmo</th><th className="n hide-sm">Objetivo</th><th className="n">FC</th><th></th></tr></thead>
        <tbody>
          {laps.filter((l) => l.distance_m >= 50).map((l) => (
            <tr key={l.i}>
              <td className="num hide-sm">{l.i}</td>
              <td><span className="row" style={{ flexWrap: 'nowrap', gap: 6 }}>
                {l.zone && <span className="zbar" style={{ ['--zc' as string]: zoneVar(zoneLevel(l.zone)) }} title={ZONE_LABEL[l.zone]} />}
                {LAP_TYPE[l.type] ?? l.type}
              </span></td>
              <td className="n">{l.distance_m >= 1000 ? `${(l.distance_m / 1000).toFixed(2)} km` : `${Math.round(l.distance_m)} m`}</td>
              <td className="n">{fmtPace(l.pace)}{l.target && <div className="small muted only-mobile">{fmtPace(l.target[0])}–{fmtPace(l.target[1])}</div>}</td>
              <td className="n muted hide-sm">{l.target ? `${fmtPace(l.target[0])}–${fmtPace(l.target[1])}` : ''}</td>
              <td className="n">{l.avg_hr ?? ''}</td>
              <td className="n"><StatusChip r={l} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function ActivityAnalysisSheet({ activityId, title, onClose, initial = 'route' }: { activityId: number; title: string; onClose: () => void; initial?: 'route' | 'plan' }) {
  const [view, setView] = useState<'route' | 'plan'>(initial)
  return (
    <Sheet title={title} onClose={onClose} labelledBy="an-title">
      <div style={{ marginBottom: 12 }}><Segmented label="Vista" value={view} onChange={setView} options={[['route', 'Mapa y gráficas'], ['plan', 'Real vs plan']]} /></div>
      {view === 'route' ? <ActivityDetail activityId={activityId} /> : <PlanCompare activityId={activityId} />}
    </Sheet>
  )
}

function PlanCompare({ activityId }: { activityId: number }) {
  const [a, setA] = useState<Analysis | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = (refresh = false) => {
    setErr(null)
    api.get<Analysis>(`/api/activities/${activityId}/analysis${refresh ? '?refresh=true' : ''}`).then(setA).catch((e) => setErr(e.message))
  }
  useEffect(() => { load() }, [activityId])  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      {err ? <Banner tone="bad">{err}</Banner> : !a ? <><Skeleton h={28} /><Skeleton h={180} style={{ marginTop: 12 }} /></> : (
        <div className="stack">
          {a.planned_title ? <div className="small muted">Comparado con: <b>{a.planned_title}</b></div>
            : <Banner tone="info">Sin entreno de OpenRun asociado: se muestran las vueltas y la nota de cumplimiento de Garmin.</Banner>}
          <AnalysisSummary a={a} />
          <LapsTable laps={a.laps} />
          <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => load(true)}><Icon name="refresh" size={16} />Recalcular</button>
        </div>
      )}
    </>
  )
}
