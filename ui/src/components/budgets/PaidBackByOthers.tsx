import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
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
    <div className="mt-1.5 space-y-1.5 text-sm">
      <button
        type="button"
        className="flex w-full justify-between gap-3 text-left rounded min-h-[44px] sm:min-h-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent/60"
        aria-expanded={open}
        aria-controls="budgets-paid-back"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="inline-flex items-center gap-1 text-slate-400">
          Paid back by others
          <ChevronDown aria-hidden="true" className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
        </span>
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
                {/* The label names the payer and what it netted ("Sam £60.00, Pizza Express"). */}
                <span className="min-w-0 text-slate-300">{m.label}</span>
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
