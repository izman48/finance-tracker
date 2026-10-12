import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Sheet from '../ui/Sheet'
import { useConfirm } from '../ui/ConfirmDialog'
import ClaudeMarker from '../changes/ClaudeMarker'
import { EditAllPanel, SuggestAgainPanel } from './ManageModes'
import { categoryColor } from '../../lib/categoryColors'
import {
  addOptions,
  checkRows,
  claudeFooter,
  editAllEntries,
  editAllTotal,
  focusAfterWrite,
  suggestDiff,
  limitError,
  manageSubtitle,
  money,
  type Budget,
  type BudgetEntry,
  type BudgetsResponse,
  type DiffRow,
  type SuggestResponse,
} from '../../lib/budgets'

export type ManageSheetProps = {
  data: BudgetsResponse
  /** The user's categories (transaction facets), for Add budget. */
  categories: string[]
  /** The last write's failure, in the spec's words (never server text). */
  message: string | null
  onClose: () => void
  // Each resolves once the API has answered and the list refetched; rejects on failure.
  onAdd: (category: string, limit: number) => Promise<void>
  onSaveLimit: (budget: Budget, limit: number) => Promise<void>
  onTogglePause: (budget: Budget) => Promise<void>
  onRemove: (budget: Budget) => Promise<void>
  /** Edit all and Suggest again: one all-or-nothing PUT of these entries. */
  onSaveAll: (entries: BudgetEntry[]) => Promise<void>
  /** Suggest again: the dry proposal (writes nothing). */
  onSuggest: () => Promise<SuggestResponse>
}

type SuggestLoad = { status: 'loading' } | { status: 'error' } | { status: 'ready'; diff: ReturnType<typeof suggestDiff> }

const SMALL_BUTTON = 'btn-ghost !px-3 !py-1.5 text-sm min-h-[44px] sm:min-h-0'
const LINK_BUTTON = 'btn-link text-xs min-h-[44px] sm:min-h-0'

/**
 * Manage budgets (concept section 13): every budget in one place, active and
 * paused, with Edit, Pause or Resume and Remove per row, and Add budget.
 * Nothing changes on screen until the API has answered (no optimism).
 */
export default function ManageSheet(props: ManageSheetProps) {
  const { data, categories, message, onClose, onAdd, onSaveLimit, onTogglePause, onRemove, onSaveAll, onSuggest } = props
  const confirm = useConfirm()
  const [busy, setBusy] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ id: string; value: string; error: string | null } | null>(null)
  const [adding, setAdding] = useState<{ category: string; value: string; error: string | null } | null>(null)
  const asking = useRef(false)
  const [mode, setMode] = useState<'list' | 'editAll' | 'suggest'>('list')
  const [values, setValues] = useState<Record<string, string>>({})
  const [allErrors, setAllErrors] = useState<Record<string, string>>({})
  const [announced, setAnnounced] = useState('')
  const [suggest, setSuggest] = useState<SuggestLoad>({ status: 'loading' })
  const [diffRows, setDiffRows] = useState<DiffRow[]>([])
  const [suggestDirty, setSuggestDirty] = useState(false)
  const [nothing, setNothing] = useState(false)

  const sheet = useRef<HTMLDivElement>(null)

  /** BM19: the focused control may have unmounted; land on one that still exists. */
  const refocus = (kind: 'edit' | 'add' | 'remove', id: string | null) => {
    const root = sheet.current?.closest<HTMLElement>('[role="dialog"]')
    // Two frames: after the refetched list and the cleared busy state have rendered.
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        const add = root?.querySelector<HTMLButtonElement>('[data-focus="add"]')
        const target = root?.matches(focusAfterWrite(kind, id, !!add && !add.disabled))
          ? root
          : root?.querySelector<HTMLElement>(focusAfterWrite(kind, id, !!add && !add.disabled))
        ;(target ?? root)?.focus()
      }),
    )
  }

  const run = async (key: string, action: () => Promise<void>, done?: () => void) => {
    setBusy(key)
    try {
      await action()
      done?.()
    } catch {
      // The panel shows the message; the row stays as it was so nothing is lost.
    } finally {
      setBusy(null)
    }
  }

  const close = async () => {
    if (busy || asking.current) return
    const original = editing && data.budgets.find((b) => b.id === editing.id)
    const editAllDirty = mode === 'editAll' && editAllEntries(data.budgets, values).budgets.length + Object.keys(editAllEntries(data.budgets, values).errors).length > 0
    const dirty =
      (editing && original && editing.value !== String(original.limit_pounds)) ||
      (adding && (adding.category || adding.value)) ||
      editAllDirty ||
      (mode === 'suggest' && suggestDirty)
    if (dirty) {
      asking.current = true
      const discard = await confirm({ title: 'Discard your changes?', confirmLabel: 'Discard', cancelLabel: 'Keep editing' })
      asking.current = false
      if (!discard) return
    }
    if (mode !== 'list') return backToList(mode === 'editAll' ? 'edit-all' : 'suggest-again')
    onClose()
  }

  const backToList = (focus: 'edit-all' | 'suggest-again') => {
    setMode('list')
    setAllErrors({})
    setNothing(false)
    requestAnimationFrame(() =>
      requestAnimationFrame(() =>
        sheet.current?.closest('[role="dialog"]')?.querySelector<HTMLElement>(`[data-focus="${focus}"]`)?.focus(),
      ),
    )
  }

  const startEditAll = () => {
    setValues({})
    setAllErrors({})
    setAnnounced(editAllTotal(data.budgets, {}))
    setMode('editAll')
  }

  const saveAll = () => {
    const checked = editAllEntries(data.budgets, values)
    setAllErrors(checked.errors)
    if (Object.keys(checked.errors).length) {
      return requestAnimationFrame(() =>
        sheet.current?.closest('[role="dialog"]')?.querySelector<HTMLInputElement>('input[aria-invalid="true"]')?.focus(),
      )
    }
    if (checked.budgets.length === 0) return backToList('edit-all')
    run('save-all', () => onSaveAll(checked.budgets), () => backToList('edit-all'))
  }

  const loadSuggest = async () => {
    setSuggest({ status: 'loading' })
    try {
      const res = await onSuggest()
      const diff = suggestDiff(res.suggestions, data.budgets)
      setDiffRows(diff.rows)
      setSuggest({ status: 'ready', diff })
    } catch {
      setSuggest({ status: 'error' })
    }
  }

  const startSuggest = () => {
    setSuggestDirty(false)
    setNothing(false)
    setAllErrors({})
    setMode('suggest')
    loadSuggest()
  }

  const saveSuggest = () => {
    const checked = checkRows(diffRows)
    setAllErrors(checked.errors)
    setNothing(checked.nothingTicked)
    const root = sheet.current?.closest('[role="dialog"]')
    if (checked.nothingTicked) return requestAnimationFrame(() => root?.querySelector<HTMLElement>('input[type="checkbox"]')?.focus())
    if (Object.keys(checked.errors).length) return requestAnimationFrame(() => root?.querySelector<HTMLElement>('input[aria-invalid="true"]')?.focus())
    run('save-suggest', () => onSaveAll(checked.budgets), () => backToList('suggest-again'))
  }

  const saveEdit = (b: Budget) => {
    if (!editing) return
    const error = limitError(editing.value)
    if (error) return setEditing({ ...editing, error })
    run(`edit-${b.id}`, () => onSaveLimit(b, Number(editing.value.trim())), () => {
      setEditing(null)
      refocus('edit', b.id)
    })
  }

  const saveAdd = () => {
    if (!adding) return
    if (!adding.category) return setAdding({ ...adding, error: 'Choose a category.' })
    const error = limitError(adding.value)
    if (error) return setAdding({ ...adding, error })
    run('add', () => onAdd(adding.category, Number(adding.value.trim())), () => {
      setAdding(null)
      refocus('add', null)
    })
  }

  const remove = async (b: Budget) => {
    const ok = await confirm({
      title: `Remove the ${b.category} budget?`,
      body: 'Your spending is not affected.',
      confirmLabel: 'Remove',
      danger: true,
    })
    if (ok) run(`remove-${b.id}`, () => onRemove(b), () => refocus('remove', b.id))
  }

  const options = addOptions(categories, data.budgets)
  const footer = claudeFooter(data.budgets)

  return (
    <Sheet title={mode === 'editAll' ? 'Edit all budgets' : mode === 'suggest' ? 'Suggest budgets again' : 'Manage budgets'} onClose={close} wide>
      <p ref={sheet} className="text-xs text-slate-400 mb-3">{manageSubtitle(data.cycle)}</p>
      {message && mode !== 'list' && (
        <div role="alert" className="banner-err text-sm mb-2">
          {message}
        </div>
      )}
      {mode === 'editAll' && (
        <EditAllPanel
          budgets={data.budgets}
          values={values}
          errors={allErrors}
          announced={announced}
          saving={busy === 'save-all'}
          onChange={(id, value) => setValues((v) => ({ ...v, [id]: value }))}
          onBlur={() => setAnnounced(editAllTotal(data.budgets, values))}
          onSave={saveAll}
          onCancel={close}
        />
      )}
      {mode === 'suggest' && (
        <SuggestAgainPanel
          load={suggest}
          rows={diffRows}
          errors={allErrors}
          nothing={nothing}
          saving={busy === 'save-suggest'}
          onRow={(i, change) => {
            setSuggestDirty(true)
            setNothing(false)
            setDiffRows((rows) => rows.map((r, j) => (j === i ? { ...r, ...change } : r)))
          }}
          onSave={saveSuggest}
          onCancel={close}
          onRetry={loadSuggest}
        />
      )}
      {mode === 'list' && (
      <>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <button
          type="button"
          data-focus="add"
          className={SMALL_BUTTON}
          disabled={!!busy || !!adding || options.length === 0}
          aria-describedby={options.length === 0 ? 'manage-add-none' : undefined}
          onClick={() => setAdding({ category: '', value: '', error: null })}
        >
          + Add budget
        </button>
        <button type="button" data-focus="suggest-again" className={SMALL_BUTTON} disabled={!!busy || !!adding || !!editing} onClick={startSuggest}>
          Suggest again
        </button>
        <button type="button" data-focus="edit-all" className={SMALL_BUTTON} disabled={!!busy || !!adding || !!editing} onClick={startEditAll}>
          Edit all
        </button>
        {options.length === 0 && (
          <span id="manage-add-none" className="text-xs text-slate-400">
            Every category you spend in already has a budget.
          </span>
        )}
      </div>

      {message && (
        <div role="alert" className="banner-err text-sm mb-2">
          {message}
        </div>
      )}

      {adding && (
        <div className="rounded-xl border border-white/[0.08] p-3 mb-2 space-y-2">
          <label className="block text-xs text-slate-400">
            Category
            <select
              className="input mt-1 min-h-[44px] sm:min-h-0"
              value={adding.category}
              onChange={(e) => setAdding({ ...adding, category: e.target.value, error: null })}
              disabled={busy === 'add'}
            >
              <option value="">Choose a category</option>
              {options.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <LimitEditor
            category={adding.category || 'the new budget'}
            value={adding.value}
            error={adding.error}
            saving={busy === 'add'}
            saveLabel="Save budget"
            onChange={(value) => setAdding({ ...adding, value, error: null })}
            onSave={saveAdd}
            onCancel={() => {
              setAdding(null)
              refocus('add', null)
            }}
          />
        </div>
      )}

      <ul className="divide-y divide-white/[0.06] border-t border-white/[0.06]">
        {data.budgets.map((b, i) => (
          <li key={b.id} className="py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={`h-2.5 w-2.5 rounded-full shrink-0 ${b.paused ? 'opacity-40' : ''}`}
                    style={{ backgroundColor: categoryColor(i) }}
                  />
                  <span className={`font-medium [overflow-wrap:anywhere] ${b.paused ? 'text-slate-400' : 'text-slate-200'}`}>
                    {b.category}
                  </span>
                  {b.paused && <span className="chip-warn">Paused</span>}
                  {b.changed_by_claude && <ClaudeMarker auditId={b.changed_by_claude.audit_id} />}
                </div>
                <p className="text-xs text-slate-400 mt-1 ml-[18px]">
                  {b.paused ? 'Not tracked, not in your totals' : `${money(b.spent)} of ${money(b.limit_pounds)} this cycle`}
                </p>
              </div>
              {editing?.id !== b.id && (
                <div className="flex items-center gap-2 shrink-0">
                  <span className="tnum font-semibold text-slate-100">{money(b.limit_pounds)}</span>
                  <button
                    type="button"
                    data-focus={`edit-${b.id}`}
                    className={SMALL_BUTTON}
                    aria-label={`Edit ${b.category}`}
                    disabled={!!busy}
                    onClick={() => setEditing({ id: b.id, value: String(b.limit_pounds), error: null })}
                  >
                    Edit
                  </button>
                </div>
              )}
            </div>
            {editing?.id === b.id && (
              <div className="mt-2">
                <LimitEditor
                  category={b.category}
                  value={editing.value}
                  error={editing.error}
                  saving={busy === `edit-${b.id}`}
                  onChange={(value) => setEditing({ ...editing, value, error: null })}
                  onSave={() => saveEdit(b)}
                  onCancel={() => {
                    setEditing(null)
                    refocus('edit', b.id)
                  }}
                />
              </div>
            )}
            <div className="flex flex-wrap gap-x-4 mt-1 ml-[18px]">
              <button
                type="button"
                className={LINK_BUTTON}
                aria-label={`${b.paused ? 'Resume' : 'Pause'} ${b.category}`}
                disabled={!!busy}
                aria-busy={busy === `pause-${b.id}`}
                onClick={() => run(`pause-${b.id}`, () => onTogglePause(b))}
              >
                {b.paused ? 'Resume' : 'Pause'}
              </button>
              <button
                type="button"
                className={`${LINK_BUTTON} !text-slate-400`}
                aria-label={`Remove ${b.category}`}
                disabled={!!busy}
                aria-busy={busy === `remove-${b.id}`}
                onClick={() => remove(b)}
              >
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>

      {footer && (
        <p className="text-xs text-slate-400 mt-3">
          {footer}{' '}
          <Link to="/changes" className="btn-link">
            See changes made by Claude →
          </Link>
        </p>
      )}
      <div className="flex justify-end mt-4">
        <button type="button" className="btn-ghost min-h-[44px] sm:min-h-0" onClick={close} disabled={!!busy}>
          Close
        </button>
      </div>
      </>
      )}
    </Sheet>
  )
}

type EditorProps = {
  category: string
  value: string
  error: string | null
  saving: boolean
  saveLabel?: string
  onChange: (value: string) => void
  onSave: () => void
  onCancel: () => void
}

/** One limit field with Save and Cancel (BM3: errors inline as an alert). */
export function LimitEditor({ category, value, error, saving, saveLabel = 'Save', onChange, onSave, onCancel }: EditorProps) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          inputMode="numeric"
          className="input !w-28 tnum text-right min-h-[44px] sm:min-h-0"
          aria-label={`Limit for ${category} (£)`}
          aria-invalid={error ? true : undefined}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && onSave()}
          disabled={saving}
          autoFocus
        />
        <button type="button" className="btn-primary !px-3 !py-1.5 min-h-[44px] sm:min-h-0" onClick={onSave} disabled={saving} aria-busy={saving}>
          {saving ? 'Saving…' : saveLabel}
        </button>
        <button type="button" className="btn-ghost !px-3 !py-1.5 min-h-[44px] sm:min-h-0" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-neg mt-1">
          {error}
        </p>
      )}
    </div>
  )
}
