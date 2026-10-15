import { Link } from 'react-router-dom'
import type { SpendingChoice as Choice } from '../../lib/projectionSpending'

// "None" is gone (owner, 2026-10-15, T-12-0): spending is always subtracted.
const OPTIONS: [Choice, string][] = [['budgets', 'My budgets'], ['average', 'Average past spending']]

export interface SpendingChoiceProps {
  shown: Choice
  budgetsAvailable: boolean
  estimate: string
  /** From the API's basis (lib/projectionSpending.evidenceLine); null while none has loaded. */
  evidence: { text: string; warn: boolean } | null
  onChoose: (choice: Choice) => void
  onEstimate: (value: string) => void
}

/** "Everyday spending" for the Wealth projection (ux T-10-15a): native
 *  radios drawn as segments, an optional estimate under Average, and one
 *  evidence line that prints the API's figure. */
export default function SpendingChoice(p: SpendingChoiceProps) {
  return (
    <fieldset className="basis-full -mt-1">
      <legend className="text-sm text-slate-300 mb-1.5">Everyday spending</legend>
      <div className="flex flex-wrap gap-2">
        {OPTIONS.map(([value, label]) => {
          const disabled = value === 'budgets' && !p.budgetsAvailable
          return (
            <label
              key={value}
              className={`${p.shown === value ? 'seg-active' : 'seg'} min-h-[44px] sm:min-h-0 inline-flex items-center cursor-pointer has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <input
                type="radio"
                name="spending-source"
                value={value}
                checked={p.shown === value}
                disabled={disabled}
                aria-describedby={disabled ? 'spending-budgets-why' : undefined}
                onChange={() => p.onChoose(value)}
                className="sr-only"
              />
              {label}
            </label>
          )
        })}
      </div>
      {!p.budgetsAvailable && (
        <p id="spending-budgets-why" className="text-xs text-slate-400 mt-1">
          Add a <Link to="/insights?section=budgets" className="text-accent underline">budget</Link> to use this.
        </p>
      )}
      {p.shown === 'average' && (
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <label htmlFor="spending-estimate" className="text-xs text-slate-400">Your own estimate (optional), £ a month</label>
          <input
            id="spending-estimate"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={p.estimate}
            onChange={(e) => p.onEstimate(e.target.value)}
            className="input !w-28 !py-1.5"
          />
          {p.estimate !== '' && (
            <button type="button" onClick={() => p.onEstimate('')} className="text-xs text-accent hover:underline">
              use measured
            </button>
          )}
        </div>
      )}
      <p aria-live="polite" className={`text-xs mt-1.5 ${p.evidence?.warn ? 'text-warn' : 'text-slate-400'}`}>
        {p.evidence?.text ?? ''}
      </p>
    </fieldset>
  )
}
