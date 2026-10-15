import type { Asset } from '../../services/api'
import { gbp0 } from '../../lib/format'
import { currentValue, daysSinceValued, investmentLine, STALE_VALUE_DAYS, updatedAgo } from '../../lib/investments'

/** One investment in Wealth's Investments group (ux T-11-2): the row button
 *  opens the holding, and "Update value" is its own button after it (never
 *  nested), as for card rows. The name renders as text. */
export default function InvestmentRow({ asset, now = Date.now(), onOpen, onUpdateValue }: {
  asset: Asset
  now?: number
  onOpen: () => void
  onUpdateValue: () => void
}) {
  const value = currentValue(asset)
  const days = daysSinceValued(asset, now)
  const stale = days !== null && days > STALE_VALUE_DAYS
  return (
    <div className="flex items-center gap-2 border-t border-white/[0.06] pr-4">
      <button
        type="button"
        id={`investment-row-${asset.id}`}
        onClick={onOpen}
        className="min-w-0 flex-1 min-h-[44px] flex items-center gap-3 pl-4 py-3 text-left hover:bg-white/[0.03] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-slate-100 truncate">{asset.name}</span>
          <span className="block text-xs text-slate-400">{investmentLine(asset)}</span>
          {asset.linked_commitment && <span className="chip-info mt-1 inline-block">Bill linked</span>}
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-sm font-semibold tnum text-slate-100">{gbp0(value)}</span>
          {days !== null && <span className="block text-xs text-slate-400">{updatedAgo(days)}</span>}
        </span>
      </button>
      <button
        type="button"
        id={`investment-update-${asset.id}`}
        onClick={onUpdateValue}
        className={`${stale ? 'chip-warn' : 'chip'} shrink-0 min-h-[44px] sm:min-h-0 px-3`}
      >Update value</button>
    </div>
  )
}
