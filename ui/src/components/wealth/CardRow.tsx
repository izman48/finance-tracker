import type { SummaryAccount } from '../../types'
import { gbp0 } from '../../lib/format'
import { cardStatementLine } from '../../lib/cardStatement'

/** A credit card on the Wealth balance sheet (ux T-10-13). Line 2 holds the
 *  statement; the figure is debt with the word "owed" for screen readers, or
 *  "in credit". The row opens card settings; `Add statement` / `Add new` are
 *  separate buttons after it, never nested inside it. */
export default function CardRow({ account, onOpen }: { account: SummaryAccount; onOpen: () => void }) {
  const owed = Number(account.credit_owed ?? 0)
  const line = cardStatementLine(account.statement)
  const detail = line.text
    ? line.withProvider ? `${account.provider_name} · ${line.text}` : line.text
    : account.provider_name
  const rowClass =
    'w-full min-h-[44px] flex items-center gap-3 px-4 py-3 text-left hover:bg-white/[0.03] transition-colors ' +
    'focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent'
  return (
    <div className="border-t border-white/[0.06]">
      <button type="button" onClick={onOpen} className={rowClass}>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-slate-100 truncate">{account.display_name}</span>
          <span className="block text-xs text-slate-400">
            {detail}
            {line.chip && <span className="chip-pos ml-2">{line.chip}</span>}
          </span>
        </span>
        <span className="chip shrink-0">live</span>
        {owed > 0 ? (
          <span className="shrink-0 text-sm font-semibold tnum text-warn">
            −{gbp0(owed)}<span className="sr-only"> owed</span>
          </span>
        ) : (
          <span className="shrink-0 text-sm font-semibold tnum text-slate-100">
            {gbp0(Math.abs(owed))}{owed < 0 ? ' in credit' : ''}
          </span>
        )}
      </button>
      {line.action && (
        <button
          type="button"
          onClick={onOpen}
          className={`${line.action === 'Add new' ? 'chip-warn' : 'text-xs text-accent underline'} ml-4 mb-3 min-h-[44px] sm:min-h-0`}
        >
          {line.action}
        </button>
      )}
    </div>
  )
}
