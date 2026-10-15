import type { Asset, Liability } from '../../services/api'
import { gbp0 } from '../../lib/format'
import { liabilityDetail, liabilityName, mortgageDetail, needsProperty } from '../../lib/liabilities'

/** One loan, finance or BNPL row in the balance sheet's "Loans and finance"
 *  group (ux T-10-0 B.1). Every figure is the API's, only formatted; the
 *  lender renders as text. A button: its text is its accessible name. */
export default function LiabilityRow({ liability, onOpen, properties = [], onChooseProperty }: {
  liability: Liability
  /** `fromChip`: the "Update balance" chip was pressed, so start on Balance. */
  onOpen?: (fromChip: boolean) => void
  /** For a mortgage's line 2 (T-12-7b): the user's property assets. */
  properties?: Asset[]
  /** A mortgage with no property: "Choose a property" opens the form. */
  onChooseProperty?: () => void
}) {
  const mortgage = liability.kind === 'mortgage'
  const owed = Number(liability.current_balance)
  const chip = liability.paid_off
    ? { className: 'chip-pos', text: 'Paid off', kind: 'paid' }
    : liability.balance_stale
      ? { className: 'chip-warn', text: 'Update balance', kind: 'stale' }
      : null
  const row = (
    <button
      type="button"
      id={`liability-row-${liability.id}`}
      onClick={(e) => onOpen?.(Boolean((e.target as HTMLElement).closest?.('[data-chip="stale"]')))}
      className="w-full min-h-[44px] flex items-center gap-3 px-4 py-3 border-t border-white/[0.06] text-left hover:bg-white/[0.03] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
    >
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-slate-100 truncate">{liabilityName(liability)}</span>
        <span className="block text-xs text-slate-400">{mortgage ? mortgageDetail(liability, properties) : liabilityDetail(liability)}</span>
        {mortgage && liability.linked_commitment && <span className="chip-info mt-1 inline-block">Bill linked</span>}
        {/* Narrow widths: the chip gets its own line so the lender keeps its room (ux on #185). */}
        {chip && <span data-chip={chip.kind} className={`${chip.className} mt-1 inline-block sm:hidden`}>{chip.text}</span>}
      </span>
      {chip && <span data-chip={chip.kind} className={`${chip.className} shrink-0 hidden sm:inline-flex`}>{chip.text}</span>}
      <span className={`shrink-0 text-sm font-semibold tnum ${owed > 0 ? 'text-warn' : 'text-slate-100'}`}>
        {owed > 0 ? '−' : ''}
        {gbp0(owed)}
      </span>
    </button>
  )
  if (!needsProperty(liability) || !onChooseProperty) return row
  // A separate button after the row, never nested inside it.
  return (
    <div>
      {row}
      <button type="button" onClick={onChooseProperty} className="text-xs text-accent underline ml-4 mb-3 min-h-[44px] sm:min-h-0">
        Choose a property
      </button>
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

/** A loan typed in as a balance-sheet item and a liability both count (A8).
 *  Not dismissible; it goes once no loan-type asset is left. */
export function BothCountedNotice({ onReplace }: { onReplace?: () => void }) {
  return (
    <div className="banner-info mx-4 my-3 flex flex-wrap items-center gap-3">
      <span className="min-w-0 flex-1">
        You have a loan entered as a balance sheet item and a loan in this list. Both count towards what you
        owe. If they are the same debt, replace the old entry.
      </span>
      {onReplace && (
        <button type="button" className="btn-ghost shrink-0" onClick={onReplace}>
          Replace an entry
        </button>
      )}
    </div>
  )
}
