import { dipSentence, paydayFigures, type BudgetProjection } from '../../lib/budgetProjection'

const SOLID = '#2DD4A7'
const DOTTED = '#38BDF8'

/** Under the chart's heading when budgets show on it: both lines, by pattern and name (BC10). */
export function BudgetLegend() {
  return (
    <div className="flex flex-wrap gap-4 text-xs text-slate-400 mb-1">
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="w-4 border-t-2 border-solid" style={{ borderColor: SOLID }} />
        Scheduled
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="w-4 border-t-2 border-dotted" style={{ borderColor: DOTTED }} />
        After your budgets
      </span>
    </div>
  )
}

const Figure = ({ amount, negative }: { amount: string; negative: boolean }) => (
  <b className={`tnum ${negative ? 'text-neg' : 'text-slate-100'}`}>{amount}</b>
)

/**
 * The text equivalent of the chart's budget line (T-09-15): the two payday
 * figures as the API sent them. Nothing here changes safe to spend or
 * "Lowest point".
 */
export function BudgetStrip({ projection }: { projection: BudgetProjection }) {
  const f = paydayFigures(projection)
  const dip = dipSentence(projection)
  return (
    <div className="mt-4 pt-4 border-t border-white/[0.06]">
      <p className="text-sm text-slate-300">
        On payday: <Figure {...f.scheduled} /> scheduled · <Figure {...f.afterBudgets} /> after budgets
      </p>
      {dip && <p className="banner-info text-sm mt-3">{dip}</p>}
      <p className="text-xs text-slate-400 mt-2">
        Budgets only: spending outside your budgets isn&apos;t included. Safe to spend and “Lowest point” are unchanged.
      </p>
    </div>
  )
}
