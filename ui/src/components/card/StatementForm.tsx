import type { FormEvent } from 'react'
import { errorSummary, type StatementErrors, type StatementForm as Form } from '../../lib/statements'

/** Add or edit a statement, inline in the Statement block (ux T-10-0 A.3).
 *  Presentational: StatementBlock owns the values, checks and requests. */
export interface StatementFormProps {
  mode: 'add' | 'edit'
  form: Form
  errors: StatementErrors
  saveError: 'duplicate' | 'error' | null
  saving: boolean
  deleting: boolean
  providerName: string
  /** Editing a provider statement saves the user's own one for that period. */
  replacingProvider: boolean
  onChange: (patch: Partial<Form>) => void
  onSubmit: () => void
  onCancel: () => void
  onDelete?: () => void
  onEditDuplicate?: () => void
}

const FIELDS: { key: keyof Form; id: string; label: string; type: 'money' | 'date' }[] = [
  { key: 'statement_balance', id: 'statement-balance', label: 'Statement balance (£)', type: 'money' },
  { key: 'statement_date', id: 'statement-date', label: 'Statement date', type: 'date' },
  { key: 'due_date', id: 'statement-due', label: 'Due date', type: 'date' },
  { key: 'minimum_due', id: 'statement-minimum', label: 'Minimum payment (£), optional', type: 'money' },
]

export default function StatementForm(props: StatementFormProps) {
  const invalid = FIELDS.filter((f) => props.errors[f.key])
  const submit = (e: FormEvent) => {
    e.preventDefault()
    props.onSubmit()
  }
  return (
    <form onSubmit={submit} noValidate className="space-y-3">
      <h5 className="text-sm font-semibold text-slate-100">{props.mode === 'edit' ? 'Edit statement' : 'Add statement'}</h5>
      {props.replacingProvider && (
        <p className="text-xs text-slate-400">
          You are replacing the statement from {props.providerName} with your own figures.
        </p>
      )}
      {invalid.length > 0 && (
        <div id="statement-errors" role="alert" tabIndex={-1} className="banner-err">
          {errorSummary(invalid.length)}
        </div>
      )}
      {FIELDS.map((f) => {
        const error = props.errors[f.key]
        return (
          <div key={f.key}>
            <label htmlFor={f.id} className="label">{f.label}</label>
            <input
              id={f.id}
              type={f.type === 'date' ? 'date' : 'text'}
              inputMode={f.type === 'money' ? 'decimal' : undefined}
              value={props.form[f.key]}
              onChange={(e) => props.onChange({ [f.key]: e.target.value })}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${f.id}-error` : undefined}
              className="input"
            />
            {error && <p id={`${f.id}-error`} className="text-xs text-neg mt-1">{error}</p>}
          </div>
        )
      })}
      {props.saveError === 'duplicate' && (
        <div role="alert" className="banner-err">
          You already have a statement for that date. Edit it instead.
          {props.onEditDuplicate && (
            <button type="button" onClick={props.onEditDuplicate} className="btn-ghost mt-2">Edit that statement</button>
          )}
        </div>
      )}
      {props.saveError === 'error' && (
        <div role="alert" className="banner-err">
          We could not save this statement. Nothing was changed. Check your connection and try again.
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {props.onDelete && (
          <button type="button" onClick={props.onDelete} disabled={props.deleting || props.saving} className="btn-danger mr-auto">
            {props.deleting ? 'Deleting…' : 'Delete statement'}
          </button>
        )}
        <button type="button" onClick={props.onCancel} className="btn-ghost ml-auto">Cancel</button>
        <button type="submit" disabled={props.saving || props.deleting} className="btn-primary">
          {props.saving ? 'Saving…' : 'Save statement'}
        </button>
      </div>
    </form>
  )
}
