import { useRef, useState } from 'react'
import Sheet from '../ui/Sheet'
import { useConfirm } from '../ui/ConfirmDialog'
import { checkRows, lastCyclesText, NOTHING_TICKED, suggestRows, type BudgetEntry, type SuggestResponse, type SuggestRow } from '../../lib/budgets'
import type { UndoFailure } from '../../lib/changes'

export type SuggestSheetProps = {
  load: { status: 'loading' } | { status: 'error' } | { status: 'ready'; data: SuggestResponse }
  saving: boolean
  /** The last save's failure kind, from the HTTP status only (never server text). */
  failure: UndoFailure | null
  onCancel: () => void
  onRetry: () => void
  onSave: (budgets: BudgetEntry[]) => void
}

const SAVE_FAILED = "Couldn't save the budgets. Nothing was changed. Try again."
const SAVE_UNKNOWN = "Couldn't confirm that. Your budgets may have been saved; check them before you try again."

/**
 * "Suggest budgets" (concept 4.1): one proposal per category from the median
 * of the last 3 pay cycles, editable, ticked by default. Nothing is saved
 * until Save budgets, and nothing is shown as saved before the API says so.
 */
export default function SuggestSheet({ load, saving, failure, onCancel, onRetry, onSave }: SuggestSheetProps) {
  const confirm = useConfirm()
  const dirty = useRef(false)
  const asking = useRef(false)

  // Escape, the backdrop and Cancel all come here: edits are never dropped silently.
  const close = async () => {
    if (saving || asking.current) return
    if (dirty.current) {
      asking.current = true
      const discard = await confirm({ title: 'Discard your changes?', confirmLabel: 'Discard', cancelLabel: 'Keep editing' })
      asking.current = false
      if (!discard) return
    }
    onCancel()
  }

  return (
    <Sheet title="Suggest budgets" onClose={close} wide>
      <p className="text-sm text-slate-400 mb-3">
        Based on the middle of your last 3 pay cycles, so one big shop doesn&apos;t inflate it. Change anything you like.
      </p>
      {load.status === 'loading' && <p role="status" className="text-sm text-slate-400 py-6">Working out suggestions…</p>}
      {load.status === 'error' && (
        <div role="alert" className="banner-err flex flex-col sm:flex-row sm:items-center gap-3">
          <p className="flex-1">Couldn&apos;t work out suggestions. Nothing was changed. Try again.</p>
          <button type="button" className="btn-ghost min-h-[44px] sm:min-h-0" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}
      {load.status === 'ready' && (
        <SuggestForm
          data={load.data}
          saving={saving}
          failure={failure}
          onCancel={close}
          onSave={onSave}
          onDirty={() => (dirty.current = true)}
        />
      )}
      {load.status !== 'ready' && (
        <div className="flex justify-end mt-4">
          <button type="button" className="btn-ghost min-h-[44px] sm:min-h-0" onClick={onCancel}>
            Cancel
          </button>
        </div>
      )}
    </Sheet>
  )
}

type FormProps = Omit<SuggestSheetProps, 'load' | 'onRetry'> & { data: SuggestResponse; onDirty: () => void }

function SuggestForm({ data, saving, failure, onCancel, onSave, onDirty }: FormProps) {
  const [rows, setRows] = useState<SuggestRow[]>(() => suggestRows(data.suggestions))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [nothing, setNothing] = useState(false)
  const form = useRef<HTMLDivElement>(null)

  const update = (i: number, change: Partial<SuggestRow>) => {
    onDirty()
    setNothing(false)
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...change } : r)))
  }

  const focusFirst = (selector: string) =>
    requestAnimationFrame(() => form.current?.querySelector<HTMLInputElement>(selector)?.focus())

  const save = () => {
    const checked = checkRows(rows)
    setErrors(checked.errors)
    setNothing(checked.nothingTicked)
    // Focus what needs fixing, so its message is read out.
    if (checked.nothingTicked) return focusFirst('input[type="checkbox"]')
    if (Object.keys(checked.errors).length) return focusFirst('input[aria-invalid="true"]')
    onSave(checked.budgets)
  }

  return (
    <div ref={form}>
      <ul className="divide-y divide-white/[0.06] border-t border-white/[0.06]">
        {rows.map((row, i) => (
          <li key={row.category} className="flex items-start gap-3 py-3">
            {row.available ? (
              <input
                type="checkbox"
                className="mt-1 h-5 w-5 accent-accent shrink-0"
                checked={row.checked}
                onChange={(e) => update(i, { checked: e.target.checked })}
                aria-label={`Include ${row.category}`}
                disabled={saving}
              />
            ) : (
              <span className="mt-1 h-5 w-5 shrink-0" aria-hidden="true" />
            )}
            <div className="min-w-0 flex-1">
              <p className={`font-medium [overflow-wrap:anywhere] ${row.available ? 'text-slate-200' : 'text-slate-400'}`}>
                {row.category}
                {!row.available && <span className="chip ml-2 align-middle">Not enough history yet</span>}
              </p>
              <p className="text-xs text-slate-400">
                {row.available ? lastCyclesText(data.suggestions[i]) : 'Needs 3 completed pay cycles.'}
              </p>
              {errors[row.category] && (
                <p role="alert" className="text-xs text-neg mt-1">{errors[row.category]}</p>
              )}
            </div>
            {row.available && (
              <label className="text-right shrink-0">
                <span className="block text-xs text-slate-400" aria-hidden="true">Limit (£)</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input !w-24 tnum text-right min-h-[44px] sm:min-h-0"
                  aria-label={`Limit for ${row.category} (£)`}
                  aria-invalid={errors[row.category] ? true : undefined}
                  value={row.limit}
                  onChange={(e) => update(i, { limit: e.target.value })}
                  disabled={saving || !row.checked}
                />
              </label>
            )}
          </li>
        ))}
      </ul>
      {data.commitment_covered.length > 0 && (
        <p className="text-xs text-slate-400 mt-3">Bills and rent are left out because your commitments already cover them.</p>
      )}
      {nothing && (
        <p role="alert" className="text-sm text-neg mt-3">{NOTHING_TICKED}</p>
      )}
      {failure && (
        <div role="alert" className="banner-err mt-3 text-sm">
          {failure === 'unknown' ? SAVE_UNKNOWN : SAVE_FAILED}
        </div>
      )}
      <div className="flex justify-end gap-2 mt-4">
        <button type="button" className="btn-ghost min-h-[44px] sm:min-h-0" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="button" className="btn-primary min-h-[44px] sm:min-h-0" onClick={save} disabled={saving} aria-busy={saving}>
          {saving ? 'Saving…' : 'Save budgets'}
        </button>
      </div>
    </div>
  )
}
