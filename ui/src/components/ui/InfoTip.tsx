import { useId, useRef, useState } from 'react'
import { Info } from 'lucide-react'

interface InfoTipProps {
  text: string
  /** Which side the bubble opens on. Default 'top'. */
  side?: 'top' | 'bottom'
  /** Horizontal anchor. 'center' needs room both sides; use 'left' near edges. */
  align?: 'center' | 'left' | 'right'
}

/**
 * A small "what is this number?" affordance for stat labels.
 * Trigger is a span (not a button) so it can safely live inside clickable
 * tiles; opens on hover/focus, toggles on tap, closes on Escape/blur.
 */
export default function InfoTip({ text, side = 'top', align = 'center' }: InfoTipProps) {
  const [open, setOpen] = useState(false)
  // A tap fires pointerdown → focus → click; without this guard the focus
  // handler opens the tip and the click handler immediately toggles it shut.
  const fromPointer = useRef(false)
  const id = useId()

  const pos = side === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'
  const anchor =
    align === 'center'
      ? 'left-1/2 -translate-x-1/2'
      : align === 'left'
        ? 'left-0'
        : 'right-0'

  return (
    <span className="relative inline-flex">
      <span
        role="button"
        tabIndex={0}
        aria-label="How is this calculated?"
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        className="cursor-help text-slate-500 hover:text-slate-300 focus:text-slate-300 focus:outline-none transition-colors"
        onClick={(e) => {
          e.stopPropagation()
          e.preventDefault()
          setOpen((o) => !o)
        }}
        onPointerEnter={(e) => e.pointerType === 'mouse' && setOpen(true)}
        onPointerLeave={(e) => e.pointerType === 'mouse' && setOpen(false)}
        onPointerDown={() => {
          fromPointer.current = true
        }}
        onFocus={() => {
          if (!fromPointer.current) setOpen(true)
          fromPointer.current = false
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false)
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            e.stopPropagation()
            setOpen((o) => !o)
          }
        }}
      >
        <Info className="w-3.5 h-3.5" />
      </span>
      {open && (
        <span
          role="tooltip"
          id={id}
          className={`pointer-events-none absolute z-50 ${pos} ${anchor} w-64 rounded-xl border border-white/10 bg-card2 shadow-pop p-3 text-xs font-normal normal-case tracking-normal leading-relaxed text-slate-300 text-left whitespace-normal`}
        >
          {text}
        </span>
      )}
    </span>
  )
}
