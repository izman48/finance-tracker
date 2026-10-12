import { lastCyclesText, NOTHING_TICKED, suggestDiff, type Budget, type DiffRow } from '../../lib/budgets'

const BUTTON = 'min-h-[44px] sm:min-h-0'

type EditAllProps = {
  budgets: Budget[]
  values: Record<string, string>
  errors: Record<string, string>
  /** The running total, updated on blur so it isn't read out on each keystroke. */
  announced: string
  saving: boolean
  onChange: (id: string, value: string) => void
  onBlur: () => void
  onSave: () => void
  onCancel: () => void
}

/** "Edit all budgets" (concept section 13, BM4): every limit a field, one all-or-nothing save. */
export function EditAllPanel({ budgets, values, errors, announced, saving, onChange, onBlur, onSave, onCancel }: EditAllProps) {
  return (
    <div>
      <ul className="divide-y divide-white/[0.06] border-t border-white/[0.06]">
        {budgets.map((b) => (
          <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
            <span className={`font-medium [overflow-wrap:anywhere] ${b.paused ? 'text-slate-400' : 'text-slate-200'}`}>
              {b.category}
              {b.paused && <span className="chip-warn ml-2 align-middle">Paused</span>}
            </span>
            <div className="text-right">
              <input
                type="text"
                inputMode="numeric"
                className={`input !w-28 tnum text-right ${BUTTON}`}
                aria-label={`Limit for ${b.category} (£)`}
                aria-invalid={errors[b.id] ? true : undefined}
                value={values[b.id] ?? String(b.limit_pounds)}
                onChange={(e) => onChange(b.id, e.target.value)}
                onBlur={onBlur}
                disabled={saving}
              />
              {errors[b.id] && (
                <p role="alert" className="text-xs text-neg mt-1">
                  {errors[b.id]}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
      <p aria-live="polite" className="text-sm text-slate-300 tnum mt-3">
        {announced}
      </p>
      <div className="flex justify-end gap-2 mt-4">
        <button type="button" className={`btn-ghost ${BUTTON}`} onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="button" className={`btn-primary ${BUTTON}`} onClick={onSave} disabled={saving} aria-busy={saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </div>
    </div>
  )
}

type SuggestAgainProps = {
  load: { status: 'loading' } | { status: 'error' } | { status: 'ready'; diff: ReturnType<typeof suggestDiff> }
  rows: DiffRow[]
  errors: Record<string, string>
  nothing: boolean
  saving: boolean
  onRow: (index: number, change: Partial<DiffRow>) => void
  onSave: () => void
  onCancel: () => void
  onRetry: () => void
}

/** "Suggest budgets again" (BM6): only what would change, unchanged counted; nothing saved until Save. */
export function SuggestAgainPanel({ load, rows, errors, nothing, saving, onRow, onSave, onCancel, onRetry }: SuggestAgainProps) {
  if (load.status === 'loading') return <p role="status" className="text-sm text-slate-400 py-6">Working out suggestions…</p>
  if (load.status === 'error') {
    return (
      <div role="alert" className="banner-err flex flex-col sm:flex-row sm:items-center gap-3">
        <p className="flex-1">Couldn&apos;t work out suggestions. Nothing was changed. Try again.</p>
        <button type="button" className={`btn-ghost ${BUTTON}`} onClick={onRetry}>
          Try again
        </button>
        <button type="button" className={`btn-ghost ${BUTTON}`} onClick={onCancel}>
          Cancel
        </button>
      </div>
    )
  }
  const { diff } = load
  return (
    <div>
      <p className="banner-info text-sm my-2">{diff.summary}</p>
      {rows.length > 0 && (
        <ul className="divide-y divide-white/[0.06] border-t border-white/[0.06]">
          {rows.map((row, i) => (
            <li key={row.category} className="flex items-start gap-3 py-3">
              <input
                type="checkbox"
                className="mt-1 h-5 w-5 accent-accent shrink-0"
                checked={row.checked}
                onChange={(e) => onRow(i, { checked: e.target.checked })}
                aria-label={`Include ${row.category}`}
                disabled={saving}
              />
              <div className="min-w-0 flex-1">
                <p className="font-medium text-slate-200 [overflow-wrap:anywhere]">
                  {row.category}
                  {row.change === 'New' && <span className="chip ml-2 align-middle">New</span>}
                </p>
                <p className="text-xs text-slate-400">{lastCyclesText(row.suggestion)}</p>
                {row.change !== 'New' && <p className="text-xs text-slate-300 mt-0.5">{row.change}</p>}
                {errors[row.category] && (
                  <p role="alert" className="text-xs text-neg mt-1">
                    {errors[row.category]}
                  </p>
                )}
              </div>
              <label className="text-right shrink-0">
                <span className="block text-xs text-slate-400" aria-hidden="true">Limit (£)</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className={`input !w-24 tnum text-right ${BUTTON}`}
                  aria-label={`Limit for ${row.category} (£)`}
                  aria-invalid={errors[row.category] ? true : undefined}
                  value={row.limit}
                  onChange={(e) => onRow(i, { limit: e.target.value })}
                  disabled={saving || !row.checked}
                />
              </label>
            </li>
          ))}
        </ul>
      )}
      {diff.unchanged > 0 && <p className="text-xs text-slate-400 mt-2">{diff.unchanged} unchanged</p>}
      {nothing && (
        <p role="alert" className="text-sm text-neg mt-3">
          {NOTHING_TICKED}
        </p>
      )}
      <div className="flex justify-end gap-2 mt-4">
        <button type="button" className={`btn-ghost ${BUTTON}`} onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        {rows.length > 0 && (
          <button type="button" className={`btn-primary ${BUTTON}`} onClick={onSave} disabled={saving} aria-busy={saving}>
            {saving ? 'Saving…' : 'Save budgets'}
          </button>
        )}
      </div>
    </div>
  )
}
