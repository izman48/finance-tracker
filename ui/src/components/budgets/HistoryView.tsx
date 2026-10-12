import HistoryBars, { type HistoryBar } from './HistoryBars'
import { categoryColor } from '../../lib/categoryColors'
import { dateDayMonth } from '../../lib/format'
import { money } from '../../lib/budgets'
import {
  budgetLimitText,
  cycleBarLabel,
  headline,
  keptText,
  nowBarLabel,
  showMore,
  slotLabel,
  trendText,
  type HistoryBudget,
  type HistoryCycle,
  type HistoryResponse,
} from '../../lib/budgetHistory'

export type HistoryViewProps = {
  status: 'loading' | 'error' | 'ready'
  data: HistoryResponse | null
  /** This cycle, for the hatched "Now" bar and the empty state; `spent` only sizes the bar. */
  now: { start: string; end: string; spent: number } | null
  /** Show more cycles (BH10). */
  more: 'idle' | 'loading' | 'error'
  retrying?: boolean
  onRetry: () => void
  onShowMore: () => void
}

/** With more bars than this, every other tick is left blank so dates don't collide on a phone. */
const TICKS_IN_FULL = 7

const cycleBar = (c: HistoryCycle, i: number, sparse: boolean): HistoryBar => ({
  key: c.start,
  label: cycleBarLabel(c),
  kind: c.on_target === null ? 'paused' : c.on_target ? 'within' : 'over',
  value: Number(c.total_spent),
  limit: c.on_target === null ? null : Number(c.total_limit),
  tick: sparse && i % 2 === 1 ? '' : dateDayMonth(c.start),
})

const slotBars = (b: HistoryBudget): HistoryBar[] =>
  b.cycles.map((s) => ({
    key: s.start,
    label: slotLabel(s),
    kind: !s.existed ? 'empty' : s.paused ? 'paused' : s.kept ? 'within' : 'over',
    value: Number(s.spent ?? 0),
    limit: s.existed && !s.paused ? s.limit_pounds : null,
  }))

/**
 * Spending > Budgets > Past cycles (concept 14; BH1-BH14). Every count,
 * verdict and trend is the server's. Over-limit bars are outlined, never
 * red, and nothing is called failed, missed or a streak (BH8).
 */
export default function HistoryView(props: HistoryViewProps) {
  const { status, data, now, more, retrying = false, onRetry, onShowMore } = props
  if (status === 'loading') {
    return (
      <div className="card card-pad">
        <span role="status" className="sr-only">Loading budget history…</span>
        <div aria-hidden="true" data-skeleton className="space-y-4 motion-safe:animate-pulse">
          <div className="h-6 w-2/3 rounded bg-white/[0.06]" />
          <div className="h-28 w-full rounded bg-white/[0.06]" />
        </div>
      </div>
    )
  }
  if (status === 'error' || !data) {
    return (
      <div role="alert" className="banner-err flex flex-col sm:flex-row sm:items-center gap-3">
        <p className="flex-1">Couldn&apos;t load your budget history. Your spending is unaffected. Try again.</p>
        <button type="button" className="btn-ghost min-h-[44px] sm:min-h-0" onClick={onRetry} disabled={retrying} aria-busy={retrying}>
          {retrying ? 'Trying…' : 'Try again'}
        </button>
      </div>
    )
  }
  if (data.cycles.length === 0) {
    return (
      <div className="card card-pad text-center py-8">
        <h2 className="font-display font-semibold text-slate-100 mb-1.5">History appears after your first full pay cycle</h2>
        <p className="text-sm text-slate-400 max-w-md mx-auto">
          When this cycle ends on {dateDayMonth(now?.end)} it will show here, and builds up to the last 6 cycles.
        </p>
      </div>
    )
  }

  const sparse = data.cycles.length + 1 > TICKS_IN_FULL
  const overall: HistoryBar[] = data.cycles.map((c, i) => cycleBar(c, i, sparse))
  if (now) {
    overall.push({ key: 'now', label: nowBarLabel(now.start), kind: 'now', value: now.spent, limit: null, tick: 'Now' })
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
      <section className="card card-pad" aria-labelledby="history-overall">
        <h2 id="history-overall" className="font-display font-semibold text-slate-100">Overall</h2>
        <p className="font-display font-bold text-2xl sm:text-3xl text-slate-50 mt-1.5">{headline(data)}</p>
        <p className="text-sm text-slate-400 mt-1 mb-4">
          A cycle is on target when your budgeted spending stays within the total of your limits.
        </p>
        <div className="overflow-hidden">
          <HistoryBars bars={overall} height={120} ticks />
        </div>
        <p className="text-xs text-slate-400 mt-3">
          Dashed line = your limits. Outlined bar = went over. Each bar uses the limits that applied in that cycle.
        </p>
        <table className="sr-only">
          <caption>Your budgets in each completed pay cycle</caption>
          <thead>
            <tr><th scope="col">Cycle</th><th scope="col">Limit</th><th scope="col">Spent</th><th scope="col">Result</th></tr>
          </thead>
          <tbody>
            {data.cycles.map((c) => (
              <tr key={c.start}>
                <th scope="row">{dateDayMonth(c.start)} to {dateDayMonth(c.end)}</th>
                <td>{money(c.total_limit)}</td>
                <td>{money(c.total_spent)}</td>
                <td>{c.on_target === null ? 'Paused, not counted' : c.on_target ? 'Within' : 'Over'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="border-t border-white/[0.06] mt-4 pt-4 text-sm text-slate-300">
          <span className="chip-pos mr-2">Trend</span>
          {trendText(data.trend)}
        </div>
      </section>

      <section className="card card-pad" aria-labelledby="history-by-budget">
        <h2 id="history-by-budget" className="font-display font-semibold text-slate-100">By budget</h2>
        <ul>
          {data.budgets.map((b, i) => (
            <li key={b.budget_id} className="py-3.5 border-t border-white/[0.06] first:border-t-0 sm:flex sm:items-center sm:gap-5">
              <div className="sm:w-48 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                  <span aria-hidden="true" className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: categoryColor(i) }} />
                  <span className="text-slate-200 font-medium truncate">{b.category}</span>
                </div>
                <p className="text-xs text-slate-400 mt-0.5 ml-[18px]">{budgetLimitText(b)}</p>
              </div>
              <div className="flex-1 my-2.5 sm:my-0 sm:max-w-60">
                <HistoryBars bars={slotBars(b)} height={40} />
              </div>
              <p className="text-sm font-semibold text-slate-100 sm:w-36 sm:text-right">{keptText(b)}</p>
            </li>
          ))}
        </ul>
        {more === 'error' && (
          <p role="alert" className="text-sm text-slate-300 mt-2">Couldn&apos;t load older cycles. Try again.</p>
        )}
        {showMore(data) && (
          <button
            type="button"
            className="btn-ghost w-full mt-2 min-h-[44px] sm:min-h-0"
            onClick={onShowMore}
            disabled={more === 'loading'}
            aria-busy={more === 'loading'}
          >
            {more === 'loading' ? 'Loading…' : 'Show more cycles'}
          </button>
        )}
      </section>
    </div>
  )
}
