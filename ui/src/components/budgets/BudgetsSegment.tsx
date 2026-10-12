export type BudgetsPeriod = 'cycle' | 'past'

const OPTIONS: { key: BudgetsPeriod; label: string }[] = [
  { key: 'cycle', label: 'This cycle' },
  { key: 'past', label: 'Past cycles' },
]

/** Spending > Budgets: this pay cycle, or the completed ones (concept 14). */
export default function BudgetsSegment({ value, onChange }: { value: BudgetsPeriod; onChange: (v: BudgetsPeriod) => void }) {
  return (
    <div role="group" aria-label="Budgets period" className="flex gap-0.5 mb-4">
      {OPTIONS.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={value === o.key}
          className={`${value === o.key ? 'seg-active' : 'seg'} min-h-[44px] sm:min-h-0`}
          onClick={() => onChange(o.key)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
