import type { Liability } from '../../services/api'
import { gbp0 } from '../../lib/format'
import { liabilityDetail } from '../../lib/liabilities'

/** One loan, finance or BNPL row in the balance sheet's "Loans and finance"
 *  group (ux T-10-0 B.1). Every figure is the API's, only formatted; the
 *  lender renders as text. Read-only until the add/edit form lands (T-10-10b). */
export default function LiabilityRow({ liability }: { liability: Liability }) {
  const owed = Number(liability.current_balance)
  return (
    <div className="w-full flex items-center gap-3 px-4 py-3 border-t border-white/[0.06] text-left">
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-slate-100 truncate">{liability.lender}</span>
        <span className="block text-xs text-slate-400">{liabilityDetail(liability)}</span>
      </span>
      {liability.paid_off ? (
        <span className="chip-pos shrink-0">Paid off</span>
      ) : liability.balance_stale ? (
        <span className="chip-warn shrink-0">Update balance</span>
      ) : null}
      <span className={`shrink-0 text-sm font-semibold tnum ${owed > 0 ? 'text-warn' : 'text-slate-100'}`}>
        {owed > 0 ? '−' : ''}
        {gbp0(owed)}
      </span>
    </div>
  )
}

/** The liabilities request failed while the rest of the page loaded (L-7).
 *  Fail-safe: the debt is never silently left out. */
export function LoansLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="banner-err mx-4 my-3 flex flex-wrap items-center gap-3" role="alert">
      <span className="min-w-0 flex-1">
        We could not load your loans and finance. Your net worth above may be too high until they load.
      </span>
      <button type="button" className="btn-ghost shrink-0" onClick={onRetry}>
        Try again
      </button>
    </div>
  )
}

/** A loan typed in as a balance-sheet item and a liability both count (A8). */
export function BothCountedNotice() {
  return (
    <div className="banner-info mx-4 my-3">
      You have a loan entered as a balance sheet item and a loan in this list. Both count towards what you
      owe. If they are the same debt, replace the old entry.
    </div>
  )
}
