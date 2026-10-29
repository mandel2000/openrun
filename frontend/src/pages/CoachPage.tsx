import { useEffect, useRef, useState } from 'react'
import { api, useApi } from '../api'
import { Banner, Icon, Markdown } from '../ui'

type Msg = { role: 'user' | 'assistant' | 'tool'; text: string; tools?: string[] }
type Info = { provider: string; model: string; configured: boolean }

const SUGGESTIONS = [
  'Analiza mi última semana y dime cómo voy',
  '¿Qué tiempo podría hacer en un 10K ahora mismo?',
  'Busca carreras el mes que viene que encajen en mi plan',
  'Mi HRV está baja, ¿qué hago hoy?',
]
const TOOL_LABEL: Record<string, string> = {
  get_athlete_profile: 'Leyó tu perfil', update_athlete_profile: 'Actualizó tu perfil', get_plan_overview: 'Revisó el plan',
  get_workouts: 'Consultó entrenos', get_recent_activities: 'Revisó actividades', get_readiness: 'Miró tu readiness',
  get_training_load: 'Analizó la carga', calculate_vdot: 'Calculó VDOT', create_workout: 'Creó/cambió un entreno',
  delete_workout: 'Eliminó un entreno', move_workout: 'Movió un entreno', add_extra_run: 'Añadió un rodaje',
  generate_plan: 'Generó un plan', adapt_today_to_readiness: 'Ajustó hoy', not_feeling_100: 'Redujo la carga',
  push_to_garmin: 'Envió a Garmin', get_personal_records: 'Consultó récords', get_race_predictions: 'Calculó predicciones',
  list_races: 'Revisó tus carreras', search_race_calendar: 'Buscó en Orycron', add_race: 'Apuntó una carrera', delete_race: 'Quitó una carrera',
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

  const send = async (t: string) => {
    if (!t.trim() || busy) return
    setText('')
    setStatus(null)
    const base: Msg[] = [...msgs, { role: 'user', text: t }]
    setMsgs(base)
    setBusy(true)
    const tools: string[] = []
    let answer = ''
    // live view: the whole turn (tool chips + answer so far) is re-rendered on every event
    const render = () => setMsgs([...base, ...(tools.length ? [{ role: 'tool' as const, text: '', tools: [...tools] }] : []),
      ...(answer ? [{ role: 'assistant' as const, text: answer }] : [])])
    try {
      const r = await fetch('/api/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: t }) })
      if (r.status === 401) { window.dispatchEvent(new Event('openrun:auth')); throw new Error('Sesión caducada') }
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
        {msgs.length > 0 && <button className="btn btn-sm btn-ghost" onClick={() => api.del('/api/chat').then(() => setMsgs([]))}><Icon name="plus" size={16} />Nueva conversación</button>}
      </div>
      {info.data && !info.data.configured && (
        <Banner>
          El coach no tiene proveedor configurado. Opciones sin suscripción extra en <a href="#ajustes">Ajustes › Coach IA</a> (Gemini gratis, Ollama local o tu Claude vía MCP).
        </Banner>
      )}
      <div className="msgs" aria-live="polite">
        {msgs.length === 0 && (
          <div className="card">
            <p className="text-2">Pregunta lo que quieras. El coach lee tu plan, actividades, HRV, carga, récords y carreras, y crea entrenos con ritmos calculados por tu VDOT (nunca inventados).</p>
            <div className="row">{SUGGESTIONS.map((s) => <button key={s} className="btn btn-sm btn-wrap" onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => m.role === 'tool' ? (
          <div key={i} className="toolcard">
            {[...new Set(m.tools)].map((t) => <span key={t} className="chip"><Icon name={CHANGES.test(t) ? 'zap' : 'check'} size={13} />{TOOL_LABEL[t] ?? t}</span>)}
          </div>
        ) : (
          <div key={i} className={`msg ${m.role}`}>{m.role === 'assistant' ? <Markdown text={m.text} /> : m.text}</div>
        ))}
        {busy && <div className="toolcard"><span className="chip"><Icon name="refresh" size={13} className="spin" />{status ? `${status}…` : 'Pensando…'}</span></div>}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <label className="sr-only" htmlFor="coach-input">Mensaje al coach</label>
        <textarea id="coach-input" ref={ta} rows={1} value={text} placeholder="Escribe al coach…" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(text) } }} />
        <button className="btn btn-primary btn-icon" disabled={busy || !text.trim()} aria-label="Enviar"><Icon name="send" /></button>
      </form>
    </div>
  )
}
