import { useEffect, useRef, useState } from 'react'
import { api, useApi } from '../api'
import { Banner, Icon, Markdown } from '../ui'
import { getLang, t } from '../i18n'

type Msg = { role: 'user' | 'assistant' | 'tool'; text: string; tools?: string[] }
type Info = { provider: string; model: string; configured: boolean }

const SUGGESTIONS = [
  t('Review my last week and tell me how I am doing'),
  t('What time could I run in a 10K right now?'),
  t('Find races next month that fit my plan'),
  t('My HRV is low, what should I do today?'),
]
const TOOL_LABEL: Record<string, string> = {
  get_athlete_profile: t('Read your profile'), update_athlete_profile: t('Updated your profile'), get_plan_overview: t('Checked the plan'),
  get_workouts: t('Looked up workouts'), get_recent_activities: t('Checked activities'), get_readiness: t('Checked your readiness'),
  get_training_load: t('Analysed training load'), calculate_vdot: t('Calculated VDOT'), create_workout: t('Created/changed a workout'),
  delete_workout: t('Deleted a workout'), move_workout: t('Moved a workout'), add_extra_run: t('Added a run'),
  generate_plan: t('Generated a plan'), adapt_today_to_readiness: t('Adjusted today'), not_feeling_100: t('Reduced the load'),
  push_to_garmin: t('Sent to Garmin'), get_personal_records: t('Looked up records'), get_race_predictions: t('Calculated predictions'),
  list_races: t('Checked your races'), search_race_calendar: t('Searched the race calendar'), add_race: t('Added a race'), delete_race: t('Removed a race'),
  get_missed_sessions: t('Checked missed sessions'), reschedule_missed: t('Rescheduled a session'), report_break: t('Planned your return'),
}
const CHANGES = /workout|plan|garmin|feeling|adapt|calculate|race|extra/
const PROVIDER_NAME: Record<string, string> = { anthropic: 'Claude (API)', gemini: 'Gemini', nvidia: 'NVIDIA', ollama: 'Ollama (local)', groq: 'Groq', openrouter: 'OpenRouter', openai: 'OpenAI' }

export default function CoachPage({ onChange }: { onChange: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const info = useApi<Info>('/api/coach/info')
  const end = useRef<HTMLDivElement>(null)
  const ta = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { api.get<Msg[]>('/api/chat').then(setMsgs).catch(() => {}) }, [])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, busy])
  useEffect(() => {
    const el = ta.current
    if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 160)}px` }
  }, [text])

  const [status, setStatus] = useState<string | null>(null)

  const send = async (q: string) => {
    if (!q.trim() || busy) return
    setText('')
    setStatus(null)
    const base: Msg[] = [...msgs, { role: 'user', text: q }]
    setMsgs(base)
    setBusy(true)
    const tools: string[] = []
    let answer = ''
    // live view: the whole turn (tool chips + answer so far) is re-rendered on every event
    const render = () => setMsgs([...base, ...(tools.length ? [{ role: 'tool' as const, text: '', tools: [...tools] }] : []),
      ...(answer ? [{ role: 'assistant' as const, text: answer }] : [])])
    try {
      const r = await fetch('/api/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept-Language': getLang() }, body: JSON.stringify({ message: q }) })
      if (r.status === 401) { window.dispatchEvent(new Event('openrun:auth')); throw new Error(t('Session expired')) }
      if (!r.ok || !r.body) throw new Error(`Error ${r.status}`)
      const reader = r.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let i
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, i).replace(/^data: /, '')
          buf = buf.slice(i + 2)
          if (!line.trim()) continue
          const ev = JSON.parse(line) as { type: string; delta?: string; name?: string; text?: string; reply?: string; tools?: { tool: string }[] }
          if (ev.type === 'text' && ev.delta) { answer += ev.delta; setStatus(null) }
          else if (ev.type === 'tool' && ev.name) {
            tools.push(ev.name)
            answer = '' // text written before a tool call was the model "thinking aloud"; the final reply comes after
            setStatus(TOOL_LABEL[ev.name] ?? ev.name)
          } else if (ev.type === 'status' && ev.text) setStatus(ev.text)
          else if (ev.type === 'done') {
            answer = ev.reply || answer
            if ((ev.tools ?? []).some((x) => CHANGES.test(x.tool))) onChange()
          }
          render()
        }
      }
    } catch (e) {
      setMsgs((m) => [...m, { role: 'assistant', text: `Error: ${(e as Error).message}` }])
    } finally {
      setBusy(false)
      setStatus(null)
    }
  }

  return (
    <div className="chat">
      <div className="row spread" style={{ marginBottom: 8 }}>
        {info.data && (
          <span className={`chip ${info.data.configured ? '' : 'chip-warn'}`}>
            <Icon name="sparkles" size={14} />{PROVIDER_NAME[info.data.provider] ?? info.data.provider} · {info.data.model}
          </span>
        )}
        {msgs.length > 0 && <button className="btn btn-sm btn-ghost" onClick={() => api.del('/api/chat').then(() => setMsgs([]))}><Icon name="plus" size={16} />{t('New conversation')}</button>}
      </div>
      {info.data && !info.data.configured && (
        <Banner>
          {t('The coach has no AI provider configured. Options with no extra subscription are in')} <a href="#ajustes">{t('Settings › AI coach')}</a> {t('(free Gemini or NVIDIA, local Ollama, or your Claude via MCP).')}
        </Banner>
      )}
      <div className="msgs" aria-live="polite">
        {msgs.length === 0 && (
          <div className="card">
            <p className="text-2">{t('Ask anything. The coach reads your plan, activities, HRV, load, records and races, and creates workouts with paces computed from your VDOT (never made up).')}</p>
            <div className="row">{SUGGESTIONS.map((s) => <button key={s} className="btn btn-sm btn-wrap" onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => m.role === 'tool' ? (
          <div key={i} className="toolcard">
            {[...new Set(m.tools)].map((x) => <span key={x} className="chip"><Icon name={CHANGES.test(x) ? 'zap' : 'check'} size={13} />{TOOL_LABEL[x] ?? x}</span>)}
          </div>
        ) : (
          <div key={i} className={`msg ${m.role}`}>{m.role === 'assistant' ? <Markdown text={m.text} /> : m.text}</div>
        ))}
        {busy && <div className="toolcard"><span className="chip"><Icon name="refresh" size={13} className="spin" />{status ? `${status}…` : t('Thinking…')}</span></div>}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <label className="sr-only" htmlFor="coach-input">{t('Message to the coach')}</label>
        <textarea id="coach-input" ref={ta} rows={1} value={text} placeholder={t('Write to the coach…')} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(text) } }} />
        <button className="btn btn-primary btn-icon" disabled={busy || !text.trim()} aria-label={t('Send')}><Icon name="send" /></button>
      </form>
    </div>
  )
}
