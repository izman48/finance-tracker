import { useEffect, useId, useRef, type ReactNode } from 'react'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

type Props = {
  title: string
  /** Escape, the backdrop, or a Cancel button; the caller decides (e.g. a discard prompt). */
  onClose: () => void
  children: ReactNode
  /** Wider panel on desktop (lists with a column of inputs). */
  wide?: boolean
}

/**
 * A modal sheet (budgets concept section 9): full width on a phone, a
 * centred panel on desktop. `role="dialog"`, labelled by its title; focus
 * moves in, is trapped, and returns to whatever opened it on close.
 */
export default function Sheet({ title, onClose, children, wide = false }: Props) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const node = panel.current
    // The panel itself, not its first control: content may still be loading,
    // and a control that unmounts would drop focus out of the sheet.
    node?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        close.current()
        return
      }
      if (e.key !== 'Tab' || !node) return
      const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)]
      if (items.length === 0) return
      const [head, tail] = [items[0], items[items.length - 1]]
      if (document.activeElement === node) {
        e.preventDefault()
        ;(e.shiftKey ? tail : head).focus()
      } else if (e.shiftKey && document.activeElement === head) {
        e.preventDefault()
        tail.focus()
      } else if (!e.shiftKey && document.activeElement === tail) {
        e.preventDefault()
        head.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      opener?.focus()
    }
  }, [])

  return (
    <div className="modal-backdrop" onClick={() => close.current()}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`modal-panel outline-none max-h-[90vh] overflow-y-auto ${wide ? 'sm:!max-w-xl' : ''}`}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id={titleId} className="font-display font-semibold text-lg text-slate-50 mb-1">
          {title}
        </h2>
        {children}
      </div>
    </div>
  )
}
