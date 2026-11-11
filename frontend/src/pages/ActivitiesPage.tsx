import { useState } from 'react'
import { api, fmtDate, fmtPace, fmtTime, garminActivityUrl, useApi, VERDICT } from '../api'
import ActivityAnalysisSheet from '../components/ActivityAnalysis'
import { Banner, Empty, Icon, Segmented, Skeleton } from '../ui'
import { t } from '../i18n'

export type Act = {
  id: number; date: string; name: string; sport: string; distance_m: number; duration_s: number; pace_s_km?: number
  avg_hr?: number; elevation_gain?: number | null; trimp: number; training_effect?: number; external_id?: string
  analysis?: { verdict: string | null } | null
}

const isRun = (a: Act) => a.sport === 'running' || a.sport.includes('run')

function UploadActivity({ onDone }: { onDone: (msg: string) => void }) {
  const [busy, setBusy] = useState(false)
  const upload = async (files: FileList) => {
    setBusy(true)
    const fd = new FormData()
    Array.from(files).forEach((f) => fd.append('files', f))
    try {
      const { job } = await api.post<{ job: string }>('/api/import/history', fd)
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 600))
        const j = await api.get<{ state: string; error: string | null; stats: { imported?: number; duplicates?: number } }>(`/api/import/history/${job}`)
        if (j.state === 'error') throw new Error(j.error ?? t('Import failed'))
        if (j.state === 'done') {
          onDone(j.stats.imported ? (j.stats.imported > 1 ? t('{n} activities uploaded.', { n: j.stats.imported }) : t('1 activity uploaded.')) : j.stats.duplicates ? t('That activity was already there.') : t('No runs found in the file.'))
          return
        }
      }
    } catch (e) { onDone(`Error: ${(e as Error).message}`) } finally { setBusy(false) }
  }
  return (
    <label className={`btn btn-sm${busy ? ' disabled' : ''}`} title={t('.fit, .gpx or .tcx files from any watch or app')}>
      <Icon name="upload" size={16} />{busy ? t('Uploading…') : t('Upload activity')}
      <input type="file" multiple accept=".fit,.gpx,.tcx,.gz,.zip" hidden disabled={busy} onChange={(e) => { if (e.target.files?.length) upload(e.target.files); e.target.value = '' }} />
    </label>
  )
}

/** One line of the plain facts a runner looks for: distance, time, pace, climb, heart rate. */
export function ActFacts({ a }: { a: Act }) {
  const run = isRun(a)
  const parts: React.ReactNode[] = []
  if (a.distance_m) parts.push(<span key="d"><b>{(a.distance_m / 1000).toFixed(2)}</b> km</span>)
  parts.push(<span key="t">{fmtTime(a.duration_s)}</span>)
  if (run && a.pace_s_km) parts.push(<span key="p">{fmtPace(a.pace_s_km)} /km</span>)
  if (run && a.elevation_gain) parts.push(<span key="e" title={t('Elevation gain')}>↑ {Math.round(a.elevation_gain)} m</span>)
  if (a.avg_hr) parts.push(<span key="h" title={t('Average heart rate')}><Icon name="heart" size={12} /> {Math.round(a.avg_hr)}</span>)
  return <div className="meta num act-facts">{parts}</div>
}

export default function ActivitiesPage() {
  const [days, setDays] = useState<'90' | '365'>('90')
  const { data, loading, reload } = useApi<Act[]>(`/api/activities?days=${days}`)
  const [upMsg, setUpMsg] = useState<string | null>(null)
  const [f, setF] = useState<'running' | 'strength_training' | 'all'>('running')
  const [open, setOpen] = useState<Act | null>(null)
  const list = (data ?? []).filter((a) => f === 'all' || (f === 'running' ? isRun(a) : a.sport === f))
  const runs = list.filter(isRun)
  const km = runs.reduce((s, a) => s + (a.distance_m || 0), 0) / 1000
  const climb = runs.reduce((s, a) => s + (a.elevation_gain || 0), 0)
  const secs = list.reduce((s, a) => s + (a.duration_s || 0), 0)
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="row">
          <Segmented label={t('Type')} value={f} onChange={setF} options={[['running', t('Running')], ['strength_training', t('Strength')], ['all', t('All')]]} />
          <Segmented label={t('Period')} value={days} onChange={setDays} options={[['90', t('3 months')], ['365', t('12 months')]]} />
        </div>
        <UploadActivity onDone={(m) => { setUpMsg(m); reload() }} />
      </div>
      {upMsg && <Banner tone={upMsg.startsWith('Error') ? 'bad' : 'ok'}>{upMsg}</Banner>}
      {loading && !data ? <Skeleton h={320} /> : (
        <>
          {list.length > 0 && (
            <div className="mini-stats">
              <div><span className="micro">{t('Activities')}</span><b>{list.length}</b></div>
              {runs.length > 0 && <div><span className="micro">{t('Distance')}</span><b>{Math.round(km)} <small>km</small></b></div>}
              <div><span className="micro">{t('Time')}</span><b>{Math.round(secs / 3600)} <small>h</small></b></div>
              {climb > 0 && <div><span className="micro">{t('Elevation gain')}</span><b>{Math.round(climb).toLocaleString()} <small>m</small></b></div>}
            </div>
          )}
          <div className="card">
            {list.length === 0 ? <Empty icon="activity" title={t('Nothing yet')}>{t('Connect Garmin in Settings or upload a .fit/.gpx file.')}</Empty> : (
              <div className="list">
                {list.map((a) => {
                  const url = garminActivityUrl(a.external_id)
                  const run = isRun(a)
                  return (
                    <div key={a.id} className={`list-row${run ? ' clickable' : ''}`} onClick={run ? () => setOpen(a) : undefined}
                      role={run ? 'button' : undefined} tabIndex={run ? 0 : undefined}
                      onKeyDown={run ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(a) } } : undefined}>
                      <Icon name={run ? 'activity' : a.sport.includes('strength') ? 'dumbbell' : 'heart'} className="muted" />
                      <div className="grow">
                        <div className="row" style={{ gap: 8 }}>
                          <span className="title">{a.name}</span>
                          {a.analysis?.verdict && <span className={`chip ${VERDICT[a.analysis.verdict][1]}`} style={{ height: 22, fontSize: 12 }}>{VERDICT[a.analysis.verdict][0]}</span>}
                        </div>
                        <div className="small muted">{fmtDate(a.date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}</div>
                        <ActFacts a={a} />
                      </div>
                      {url && <a className="btn btn-ghost btn-icon" href={url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} aria-label={t('View on Garmin Connect')}><Icon name="external" size={18} /></a>}
                      {run && <Icon name="chevronRight" size={18} className="muted" />}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </>
      )}
      {open && <ActivityAnalysisSheet activityId={open.id} title={open.name} laps={!!open.analysis || !!open.external_id?.startsWith('garmin:')} onClose={() => setOpen(null)} />}
    </div>
  )
}
