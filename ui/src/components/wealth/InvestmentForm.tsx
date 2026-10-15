import { useEffect, useState, type ReactNode } from 'react'
import Sheet from '../ui/Sheet'
import { useConfirm } from '../ui/ConfirmDialog'
import { assetsAPI, type Asset, type ChooseCandidate } from '../../services/api'
import { dateDayMonth, gbp } from '../../lib/format'
import { INVESTMENT_TYPES, INVESTMENT_TYPE_LABEL } from '../../lib/investments'
import {
  blankInvestment, commitmentLabel, deleteLinkedConfirm, investmentFor, SAVE_ERROR, saveInvestment, stopBillConfirm,
  type InvestmentErrors, type InvestmentField, type InvestmentFormState,
} from '../../lib/investmentForm'

export interface InvestmentFormViewProps {
  mode: 'add' | 'edit'
  /** The holding's name as saved (the edit title). */
  name: string
  form: InvestmentFormState
  errors: InvestmentErrors
  message: string | null
  saving: boolean
  /** Current accounts, the only ones a contribution may be paid from. */
  accounts: { id: string; name: string }[]
  candidates: ChooseCandidate[] | null
  choice: string | null
  linkedLabel: string | null
  onChange: (patch: Partial<InvestmentFormState>) => void
  onChoose: (id: string) => void
  onBack: () => void
  onSubmit: () => void
  onCancel: () => void
  onDelete: () => void
}

const ordinal = (n: number) => `${n}${n % 10 === 1 && n !== 11 ? 'st' : n % 10 === 2 && n !== 12 ? 'nd' : n % 10 === 3 && n !== 13 ? 'rd' : 'th'}`

/** Add or edit an investment (ux T-11-2), as markup; state lives below. */
export function InvestmentFormView(p: InvestmentFormViewProps) {
  const title = p.candidates ? 'Which bill is this?' : p.mode === 'add' ? 'Add an investment' : p.name
  return (
    <Sheet title={title} onClose={p.onCancel}>
      {p.candidates ? <BillPicker {...p} candidates={p.candidates} /> : <FormBody {...p} />}
    </Sheet>
  )
}

function FormBody(p: InvestmentFormViewProps) {
  const field = (name: InvestmentField, id: string) => ({
    id,
    disabled: p.saving,
    'aria-invalid': p.errors[name] ? true : undefined,
    'aria-describedby': p.errors[name] ? `${id}-error` : undefined,
  })
  const decimal = { type: 'text', inputMode: 'decimal' as const, autoComplete: 'off', className: 'input' }
  const box = commitmentLabel(p.form.contribution)
  return (
    <form onSubmit={(e) => { e.preventDefault(); p.onSubmit() }} noValidate className="space-y-3">
      {p.linkedLabel && <p className="text-sm text-slate-400">Linked to your bill &quot;{p.linkedLabel}&quot;.</p>}
      <Field label="Name" htmlFor="investment-name" error={p.errors.name}>
        <input {...field('name', 'investment-name')} className="input" autoComplete="off" value={p.form.name}
          onChange={(e) => p.onChange({ name: e.target.value })} />
      </Field>
      <Field label="Type" htmlFor="investment-type">
        <select id="investment-type" className="input" disabled={p.saving} value={p.form.asset_type}
          onChange={(e) => p.onChange({ asset_type: e.target.value })}>
          {INVESTMENT_TYPES.map((t) => <option key={t} value={t}>{INVESTMENT_TYPE_LABEL[t]}</option>)}
        </select>
      </Field>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Value today (£)" htmlFor="investment-value-today" error={p.errors.value}>
          <input {...field('value', 'investment-value-today')} {...decimal} value={p.form.value}
            onChange={(e) => p.onChange({ value: e.target.value })} />
        </Field>
        <Field label="Growth a year (%)" htmlFor="investment-growth" error={p.errors.growth} help="Your own guess. nilu does not look up prices.">
          <input {...field('growth', 'investment-growth')} {...decimal} value={p.form.growth}
            onChange={(e) => p.onChange({ growth: e.target.value })} />
        </Field>
      </div>
      <Field label="Monthly contribution (£)" htmlFor="investment-contribution" error={p.errors.contribution}>
        <input {...field('contribution', 'investment-contribution')} {...decimal} value={p.form.contribution}
          onChange={(e) => p.onChange({ contribution: e.target.value })} />
      </Field>
      <div>
        <label className="flex items-center gap-3 min-h-[44px] text-sm text-slate-100" htmlFor="investment-commit">
          <input id="investment-commit" type="checkbox" disabled={p.saving || !box.enabled}
            checked={p.form.commit && box.enabled} aria-expanded={p.form.commit && box.enabled}
            aria-controls="investment-bill-fields" aria-describedby="investment-commit-help"
            onChange={(e) => p.onChange({ commit: e.target.checked })} />
          {box.text}
        </label>
        <p id="investment-commit-help" className="text-xs text-slate-400">
          Counts like a bill: it lowers safe to spend and your Cashflow forecast. Your net worth stays the same, because the money moves into the investment.
        </p>
      </div>
      {p.form.commit && box.enabled && (
        <div id="investment-bill-fields" className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Pay from" htmlFor="investment-pay-from" error={p.errors.pay_from}>
            <select {...field('pay_from', 'investment-pay-from')} className="input" value={p.form.pay_from}
              onChange={(e) => p.onChange({ pay_from: e.target.value })}>
              {p.accounts.length === 0 && <option value="">No current account</option>}
              {p.accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
          <Field label="Day of the month" htmlFor="investment-day">
            <select id="investment-day" className="input" disabled={p.saving} value={p.form.day}
              onChange={(e) => p.onChange({ day: e.target.value })}>
              {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
        </div>
      )}
      {p.message && <div className="banner-err" role="alert" id="investment-errors">{p.message}</div>}
      <div className="flex flex-wrap items-center gap-2 pt-2">
        {p.mode === 'edit' && (
          <button id="investment-delete" type="button" className="btn-danger" disabled={p.saving} onClick={p.onDelete}>Delete</button>
        )}
        <span className="flex-1" />
        <button type="button" className="btn-ghost" onClick={p.onCancel}>Cancel</button>
        <button id="investment-save" type="submit" className="btn-primary" disabled={p.saving}>{p.saving ? 'Saving…' : 'Save'}</button>
      </div>
    </form>
  )
}

function BillPicker(p: InvestmentFormViewProps & { candidates: ChooseCandidate[] }) {
  const amount = gbp(Number(p.form.contribution.replace(/,/g, '')))
  return (
    <div>
      <p className="text-sm text-slate-400 mb-3">Pick the one that pays {p.form.name.trim()}, so it only counts once.</p>
      {p.message && <div className="banner-err mb-3" role="alert">{p.message}</div>}
      <fieldset className="space-y-2" id="investment-picker">
        <legend className="sr-only">Which bill is this?</legend>
        {p.candidates.map((c, i) => (
          <label key={c.id} className="flex items-start gap-3 min-h-[44px] p-2 rounded border border-white/10 text-sm">
            <input type="radio" name="investment-bill" id={i === 0 ? 'investment-bill-first' : undefined} value={c.id} checked={p.choice === c.id} onChange={() => p.onChoose(c.id)} />
            <span className="min-w-0">
              <span className="block text-slate-100">{c.label}</span>
              <span className="block text-xs text-slate-400">{gbp(Number(c.amount))} {c.cadence} · next {dateDayMonth(c.next_date)}</span>
            </span>
          </label>
        ))}
        <label className="flex items-start gap-3 min-h-[44px] p-2 rounded border border-white/10 text-sm">
          <input type="radio" name="investment-bill" value="new" checked={p.choice === 'new'} onChange={() => p.onChoose('new')} />
          <span className="min-w-0">
            <span className="block text-slate-100">None of these, add a new bill</span>
            <span className="block text-xs text-slate-400">
              nilu adds &quot;{p.form.name.trim()} contribution&quot;, {amount} monthly on the {ordinal(Number(p.form.day))}
            </span>
          </span>
        </label>
      </fieldset>
      <p id="investment-picker-hint" className="text-xs text-slate-400 mt-2">{p.choice ? '' : 'Choose one to continue.'}</p>
      <div className="flex justify-end gap-2 mt-4">
        <button type="button" className="btn-ghost" onClick={p.onBack}>Back</button>
        <button type="button" className="btn-primary" aria-disabled={!p.choice || p.saving} disabled={!p.choice || p.saving}
          aria-describedby="investment-picker-hint" onClick={p.onSubmit}>{p.saving ? 'Saving…' : 'Save'}</button>
      </div>
    </div>
  )
}

function Field({ label, htmlFor, error, help, children }: {
  label: string; htmlFor: string; error?: string; help?: string; children: ReactNode
}) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>{label}</label>
      {children}
      {help && !error && <p className="text-xs text-slate-400 mt-1">{help}</p>}
      {error && <p id={`${htmlFor}-error`} className="text-xs text-neg mt-1"><span className="sr-only">Error: </span>{error}</p>}
    </div>
  )
}

const FIELD_ORDER: [InvestmentField, string][] = [
  ['name', 'investment-name'], ['value', 'investment-value-today'], ['growth', 'investment-growth'],
  ['contribution', 'investment-contribution'], ['pay_from', 'investment-pay-from'],
]
const focusSoon = (id: string) => window.setTimeout(() => document.getElementById(id)?.focus(), 0)

/** Add or edit an investment: owns the form state, the confirmations, the
 *  picker and the round trips (lib/investmentForm.saveInvestment). */
export default function InvestmentForm({ asset, accounts, today, onClose, onSaved }: {
  asset: Asset | null
  accounts: { id: string; name: string }[]
  today: string
  onClose: () => void
  onSaved: (assetId: string | null, toast: string) => void
}) {
  const first = accounts[0]?.id ?? null
  const [form, setForm] = useState<InvestmentFormState>(() => (asset ? investmentFor(asset, first) : blankInvestment(today, first)))
  const [errors, setErrors] = useState<InvestmentErrors>({})
  const [message, setMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [candidates, setCandidates] = useState<ChooseCandidate[] | null>(null)
  const [choice, setChoice] = useState<string | null>(null)
  const [createdId, setCreatedId] = useState<string | undefined>()
  const confirm = useConfirm()

  // After the sheet has focused its panel: the first field (ux).
  useEffect(() => { focusSoon('investment-name') }, [])

  const submit = async () => {
    if (saving) return
    if (asset?.linked_commitment && !form.commit && !(await confirm(stopBillConfirm(asset)))) {
      setForm({ ...form, commit: true })
      return
    }
    setSaving(true)
    const out = await saveInvestment(assetsAPI, form, {
      asset, today, hasCurrentAccount: accounts.length > 0, createdId, commitmentChoice: candidates && choice ? choice : undefined,
    })
    setSaving(false)
    setErrors(out.kind === 'invalid' ? out.errors : {})
    setMessage(out.kind === 'message' ? out.message : out.kind === 'error' ? SAVE_ERROR : null)
    if (out.kind === 'saved') onSaved(out.assetId, asset ? `Saved ${form.name.trim()}.` : `Added ${form.name.trim()}.`)
    else if (out.kind === 'choose') {
      setCreatedId(out.assetId)
      setCandidates(out.candidates)
      setChoice(null)
      focusSoon('investment-bill-first')
    } else if (out.kind === 'invalid') {
      const target = FIELD_ORDER.find(([name]) => out.errors[name])
      if (target) focusSoon(target[1])
    }
  }

  const remove = async () => {
    if (!asset) return
    const copy = asset.linked_commitment
      ? deleteLinkedConfirm(asset)
      : { title: `Delete ${asset.name}?`, body: 'Its value and history are removed from your net worth.', confirmLabel: 'Delete', cancelLabel: 'Cancel', danger: true }
    if (!(await confirm(copy))) return
    try {
      await assetsAPI.remove(asset.id)
      onSaved(null, `Deleted ${asset.name}.`)
    } catch {
      setMessage(SAVE_ERROR)
    }
  }

  return (
    <InvestmentFormView
      mode={asset ? 'edit' : 'add'} name={asset?.name ?? ''} form={form} errors={errors} message={message} saving={saving}
      accounts={accounts} candidates={candidates} choice={choice} linkedLabel={asset?.linked_commitment?.label ?? null}
      onChange={(patch) => setForm({ ...form, ...patch })} onChoose={setChoice}
      onBack={() => { setCandidates(null); focusSoon('investment-save') }}
      onSubmit={submit} onCancel={() => (createdId ? onSaved(createdId, `Added ${form.name.trim()}.`) : onClose())} onDelete={remove}
    />
  )
}
