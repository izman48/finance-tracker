import { differenceSentence, dipSentence, stripFigures, stripTitle, STRIP_FOOTNOTE, type BudgetProjection } from '../../lib/budgetProjection'

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
        If you spend your budgets
      </span>
    </div>
  )
}

/**
 * "Your balance on payday" (concept 12): the text equivalent of the chart's
 * budget line. Three figures as the API sent them; nothing here changes safe
 * to spend or "Lowest point".
 */
export function BudgetStrip({ projection }: { projection: BudgetProjection }) {
  const difference = differenceSentence(projection)
  const dip = dipSentence(projection)
  return (
    <div className="mt-4 pt-4 border-t border-white/[0.06]">
      <p className="text-xs text-slate-400 mb-2">{stripTitle(projection)}</p>
      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
        {stripFigures(projection).map((f) => (
          <div key={f.label} className="flex sm:flex-col justify-between gap-2 items-start">
            <div>
              <dt className="flex items-center gap-2 text-sm text-slate-200">
                {f.line === 'none' ? (
                  <span aria-hidden="true" className="w-4 text-center text-slate-400">≈</span>
                ) : (
                  <span
                    aria-hidden="true"
                    className={`w-4 border-t-2 ${f.line === 'dotted' ? 'border-dotted' : 'border-solid'}`}
                    style={{ borderColor: f.line === 'dotted' ? DOTTED : SOLID }}
                  />
                )}
                {f.label}
              </dt>
              <p className="text-xs text-slate-400 mt-0.5">{f.explain}</p>
            </div>
            <dd className={`font-display font-semibold text-xl tnum ${f.negative ? 'text-neg' : 'text-slate-100'}`}>{f.amount}</dd>
          </div>
        ))}
      </dl>
      {dip && <p className="banner-info text-sm mt-3">{dip}</p>}
      <p className="text-xs text-slate-400 mt-3">
        {STRIP_FOOTNOTE}
        {difference && <> {difference}</>}
      </p>
    </div>
  )
}
