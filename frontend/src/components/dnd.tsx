import { useCallback, useEffect, useRef, useState } from 'react'
import type { Workout } from '../api'

// Pointer-based drag & drop for plan sessions. HTML5 drag events don't fire on touch screens, so
// this handles mouse (drag after 5 px) and touch (long press, then drag) the same way.
// Drop targets are any element with data-drop-date="YYYY-MM-DD".

export type DragState = { w: Workout; x: number; y: number; over: string | null } | null

const LONG_PRESS_MS = 350

function targetAt(x: number, y: number): string | null {
  const el = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-drop-date]')
  return el?.dataset.dropDate ?? null
}

export function useWorkoutDrag(onDrop: (w: Workout, date: string) => void, canDrop: (date: string) => boolean) {
  const [drag, setDrag] = useState<DragState>(null)
  const dragRef = useRef<DragState>(null)
  const suppressClick = useRef(false)
  const set = (d: DragState) => { dragRef.current = d; setDrag(d) }

  useEffect(() => {
    if (!drag) return
    document.body.classList.add('dragging')
    const block = (e: TouchEvent) => e.preventDefault() // stop the page scrolling while dragging on touch
    document.addEventListener('touchmove', block, { passive: false })
    return () => { document.body.classList.remove('dragging'); document.removeEventListener('touchmove', block) }
  }, [!!drag]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback((w: Workout, e: React.PointerEvent) => {
    if (e.button !== 0) return
    const x0 = e.clientX
    const y0 = e.clientY
    const touch = e.pointerType !== 'mouse'
    let started = false
    let timer: number | undefined
    const begin = (x: number, y: number) => {
      started = true
      suppressClick.current = true
      if (touch && navigator.vibrate) navigator.vibrate(15)
      set({ w, x, y, over: targetAt(x, y) })
    }
    const move = (ev: PointerEvent) => {
      if (started) {
        const over = targetAt(ev.clientX, ev.clientY)
        set({ w, x: ev.clientX, y: ev.clientY, over: over && canDrop(over) ? over : null })
        // auto-scroll near the screen edges
        if (ev.clientY < 70) window.scrollBy(0, -12)
        else if (ev.clientY > window.innerHeight - 90) window.scrollBy(0, 12)
        return
      }
      const moved = Math.hypot(ev.clientX - x0, ev.clientY - y0)
      if (touch) { if (moved > 8) cleanup() } // it's a scroll, not a long press
      else if (moved > 5) begin(ev.clientX, ev.clientY)
    }
    const up = () => {
      const d = dragRef.current
      cleanup()
      if (started && d?.over && d.over !== w.date) onDrop(w, d.over)
      set(null)
      window.setTimeout(() => { suppressClick.current = false }, 0)
    }
    const cleanup = () => {
      window.clearTimeout(timer)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
    }
    if (touch) timer = window.setTimeout(() => begin(x0, y0), LONG_PRESS_MS)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
  }, [onDrop, canDrop])

  return { drag, start, suppressClick }
}

export function DragGhost({ drag }: { drag: DragState }) {
  if (!drag) return null
  return (
    <div className="drag-ghost" style={{ left: drag.x, top: drag.y }} aria-hidden>
      <b>{drag.w.title}</b>
      <span>{drag.over ? `→ ${new Date(drag.over + 'T12:00').toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric' })}` : 'Suelta en un día'}</span>
    </div>
  )
}
