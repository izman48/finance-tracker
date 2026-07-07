import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Info } from 'lucide-react'

interface InfoTipProps {
  text: string
  /** Which side the bubble opens on. Default 'top'. */
  side?: 'top' | 'bottom'
  /** Kept for API compatibility; the bubble now centers on the trigger and
   *  clamps to the viewport, so it never needs a manual edge anchor. */
  align?: 'center' | 'left' | 'right'
}

const WIDTH = 256 // w-64

/**
 * A small "what is this number?" affordance for stat labels.
 * The bubble is rendered in a portal on <body> and positioned `fixed` against
 * the trigger, so an ancestor with `overflow-hidden` (e.g. the safe-to-spend
 * hero card) can never clip it. Opens on hover/focus, toggles on tap.
 */
export default function InfoTip({ text, side = 'top' }: InfoTipProps) {
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState<{ left: number; top?: number; bottom?: number }>({ left: 0 })
  const triggerRef = useRef<HTMLSpanElement>(null)
  // A tap fires pointerdown → focus → click; without this guard the focus
  // handler opens the tip and the click handler immediately toggles it shut.
  const fromPointer = useRef(false)
  const id = useId()

  const place = () => {
    const r = triggerRef.current?.getBoundingClientRect()
    if (!r) return
    const half = WIDTH / 2
    const left = Math.min(Math.max(r.left + r.width / 2, half + 8), window.innerWidth - half - 8)
    setCoords(
      side === 'top'
        ? { left, bottom: window.innerHeight - r.top + 8 }
        : { left, top: r.bottom + 8 },
    )
  }

  const show = () => {
    place()
    setOpen(true)
  }

  return (
    <span className="relative inline-flex">
      <span
        ref={triggerRef}
        role="button"
        tabIndex={0}
        aria-label="How is this calculated?"
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        className="cursor-help text-slate-500 hover:text-slate-300 focus:text-slate-300 focus:outline-none transition-colors"
        onClick={(e) => {
          e.stopPropagation()
          e.preventDefault()
          setOpen((o) => {
            if (!o) place()
            return !o
          })
        }}
        onPointerEnter={(e) => e.pointerType === 'mouse' && show()}
        onPointerLeave={(e) => e.pointerType === 'mouse' && setOpen(false)}
        onPointerDown={() => {
          fromPointer.current = true
        }}
        onFocus={() => {
          if (!fromPointer.current) show()
          fromPointer.current = false
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false)
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            e.stopPropagation()
            setOpen((o) => {
              if (!o) place()
              return !o
            })
          }
        }}
      >
        <Info className="w-3.5 h-3.5" />
      </span>
      {open &&
        typeof document !== 'undefined' &&
        createPortal(
          <span
            role="tooltip"
            id={id}
            style={{ position: 'fixed', left: coords.left, top: coords.top, bottom: coords.bottom, transform: 'translateX(-50%)' }}
            className="pointer-events-none z-[100] w-64 rounded-xl border border-white/10 bg-card2 shadow-pop p-3 text-xs font-normal normal-case tracking-normal leading-relaxed text-slate-300 text-left whitespace-normal"
          >
            {text}
          </span>,
          document.body,
        )}
    </span>
  )
}
