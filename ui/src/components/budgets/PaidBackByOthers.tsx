import { useState } from 'react'
import { gbp } from '../../lib/format'
import type { NotCounted } from '../../lib/budgets'

const HELPER = "Friends' repayments you marked. They reduce what counts as spending here and are never income."

/**
 * "Paid back by others" in the budgets' Not counted list (T-03-6; PRD T-03-1
 * Screens 3): the total as the API sent it, a toggle listing each mark and
 * what it netted, and any excess, which is never income. Absent at £0.
 * Labels come from bank text and Claude: rendered as text only.
 */
export default function PaidBackByOthers({ notCounted, defaultOpen = false }: { notCounted: NotCounted; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const total = Number(notCounted.paid_back ?? 0)
  if (total <= 0) return null
  return (
    <div className="space-y-1.5 text-sm">
      <button
        type="button"
        className="flex w-full justify-between gap-3 text-left min-h-[44px] sm:min-h-0"
        aria-expanded={open}
        aria-controls="budgets-paid-back"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-slate-400 underline decoration-dotted underline-offset-2">Paid back by others</span>
        <span className="tnum text-slate-100">{gbp(total)}</span>
      </button>
      {(notCounted.paid_back_excess ?? []).map((e) => (
        <p key={e.category} className="text-xs text-slate-400">
          {gbp(Number(e.amount))} was more than you spent in {e.category} this cycle. It isn&apos;t income.
        </p>
      ))}
      {open && (
        <div id="budgets-paid-back" className="space-y-1.5">
          <ul className="space-y-1">
            {(notCounted.paid_back_marks ?? []).map((m, i) => (
              <li key={i} className="flex justify-between gap-3">
                <span className="min-w-0 text-slate-300">
                  {m.label} <span className="text-slate-400">{m.against}</span>
                </span>
                <span className="tnum text-slate-100">{gbp(Number(m.amount))}</span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-slate-400">{HELPER}</p>
        </div>
      )}
    </div>
  )
}
