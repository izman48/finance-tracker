import type { PlanErrors, PlanField, PlanFormState } from '../../lib/cardPlans'

const FIELDS: { name: PlanField; label: string; type: 'text' | 'date'; inputMode?: 'decimal' | 'numeric' }[] = [
  { name: 'name', label: 'Name', type: 'text' },
  { name: 'balance', label: 'Left to pay (£)', type: 'text', inputMode: 'decimal' },
  { name: 'instalment', label: 'Monthly instalment (£)', type: 'text', inputMode: 'decimal' },
  { name: 'fee', label: 'Monthly fee (£), optional', type: 'text', inputMode: 'decimal' },
  { name: 'payments', label: 'Payments left', type: 'text', inputMode: 'numeric' },
  { name: 'next_date', label: 'Next payment date', type: 'date' },
  { name: 'apr', label: 'Interest rate (% APR), optional', type: 'text', inputMode: 'decimal' },
]

/** The plan form (ux T-12-1 "Plans"): labelled fields, each error tied to
 *  its field. Shown inside a Sheet by the Instalment plans block. */
export default function PlanForm({ value, errors, saving, onChange, onCancel, onSave }: {
  value: PlanFormState
  errors: PlanErrors
  saving: boolean
  onChange: (patch: Partial<PlanFormState>) => void
  onCancel: () => void
  onSave: () => void
}) {
  return (
    <form noValidate onSubmit={(e) => { e.preventDefault(); onSave() }} className="space-y-3">
      {FIELDS.map((f) => {
        const id = `plan-${f.name}`
        const error = errors[f.name]
        return (
          <div key={f.name}>
            <label htmlFor={id} className="label">{f.label}</label>
            <input
              id={id}
              type={f.type}
              inputMode={f.inputMode}
              autoComplete="off"
              value={value[f.name]}
              onChange={(e) => onChange({ [f.name]: e.target.value })}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${id}-error` : undefined}
              className="input"
            />
            {error && <p id={`${id}-error`} className="text-xs text-warn mt-1">{error}</p>}
          </div>
        )
      })}
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" onClick={onCancel} className="btn-ghost">Cancel</button>
        <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Saving…' : 'Save plan'}</button>
      </div>
    </form>
  )
}
