/** The key under the net worth graph (T-11-6, ux T-11-2): each group is
 *  both its line's switch and its figure, and the figures add up to net
 *  worth. Showing or hiding a line never changes a figure. */
import { gbp0 as gbp } from '../../lib/format'
import { NET_WORTH_COLOUR, type GroupKey, type KeyRow } from '../../lib/netWorthLines'

export interface NetWorthKeyProps {
  rows: KeyRow[]
  netWorth: number
  shown: GroupKey[]
  includeInvestments: boolean
  hasInvestments: boolean
  announcement: string
  onToggle: (key: GroupKey) => void
  onIncludeInvestments: (include: boolean) => void
}

function money(value: number) {
  return value < 0 ? `−${gbp(Math.abs(value))}` : gbp(value)
}

export default function NetWorthKey(p: NetWorthKeyProps) {
  const netWorthName = p.includeInvestments ? 'Net worth' : 'Net worth without investments'
  return (
    <div className="mt-4">
      <h3 id="nw-key-heading" className="text-xs uppercase tracking-wider text-slate-400 mb-1.5">Show on graph</h3>
      <div role="group" aria-labelledby="nw-key-heading" className="divide-y divide-white/[0.05]">
        {p.rows.map((row) => {
          const on = p.shown.includes(row.key)
          const swatch = (
            <span
              aria-hidden="true"
              className="inline-block w-4 shrink-0 border-t-[3px]"
              style={{ borderColor: row.colour, borderTopStyle: on ? 'solid' : 'dotted' }}
            />
          )
          const figure = (
            <span className={`tnum ${row.key === 'debt' ? 'text-warn' : 'text-slate-200'}`}>{money(row.value)}</span>
          )
          if (!row.included) {
            return (
              <div key={row.key} className="flex items-center gap-3 min-h-[44px] px-1">
                {swatch}
                <span className="flex-1 min-w-0 text-slate-300">{row.label}</span>
                {figure}
                <span className="text-xs text-slate-400 w-24 shrink-0 whitespace-nowrap text-right">Not included</span>
              </div>
            )
          }
          return (
            <button
              key={row.key}
              type="button"
              aria-pressed={on}
              aria-label={`${row.label}, ${money(row.value)}, line ${on ? 'shown' : 'hidden'}`}
              onClick={() => p.onToggle(row.key)}
              className="w-full flex items-center gap-3 min-h-[44px] px-1 text-left rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
            >
              {swatch}
              <span className="flex-1 min-w-0 text-slate-300">{row.label}</span>
              {figure}
              <span className="text-xs text-slate-400 w-24 shrink-0 whitespace-nowrap text-right">{on ? 'Hide' : 'Show'}</span>
            </button>
          )
        })}
        <div className="flex items-center gap-3 min-h-[44px] px-1">
          <span aria-hidden="true" className="inline-block w-4 shrink-0 border-t-[3px]" style={{ borderColor: NET_WORTH_COLOUR }} />
          <span className="flex-1 min-w-0 text-slate-100 font-medium">{netWorthName}</span>
          <span className="tnum text-slate-50 font-medium">{money(p.netWorth)}</span>
          <span className="text-xs text-slate-400 w-24 shrink-0 whitespace-nowrap text-right">Always shown</span>
        </div>
      </div>
      {p.hasInvestments && (
        <label className="mt-2 flex items-center gap-2 min-h-[44px] px-1 text-sm text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={p.includeInvestments}
            onChange={(e) => p.onIncludeInvestments(e.target.checked)}
            className="h-4 w-4 accent-accent"
          />
          Include investments in net worth
        </label>
      )}
      <p className="sr-only" aria-live="polite">{p.announcement}</p>
    </div>
  )
}
