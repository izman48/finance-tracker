import { useEffect, useRef, useState, type ReactNode } from 'react'
import { liabilitiesAPI, type Asset, type ChooseCandidate, type Liability } from '../../services/api'
import { dateLong, gbp0, money } from '../../lib/format'
import { latestValue } from '../../lib/assets'
import {
  addedToast, blankForm, deleteConfirm, FOCUS, focusAfter, formFor, kindChange, NOT_FOUND, optOutConfirm, replaceConfirm,
  SAVE_ERROR, saveLiability, type FieldErrors, type FieldName, type LiabilityFormState,
} from '../../lib/liabilityForm'
import { useConfirm } from '../ui/ConfirmDialog'
import { useToast } from '../ui/Toast'

const KINDS: [Liability['kind'], string][] = [
  ['loan', 'Loan'], ['finance', 'Retail finance'], ['bnpl', 'Buy now pay later'], ['mortgage', 'Mortgage'],
]

const CADENCES: [Liability['cadence'], string][] = [
  ['monthly', 'Monthly'], ['weekly', 'Weekly'], ['fortnightly', 'Every 2 weeks'], ['four_weekly', 'Every 4 weeks'],
]
const CADENCE_WORD: Record<string, string> = { monthly: 'monthly', weekly: 'weekly', custom_days: 'every few weeks' }

export interface LiabilityFormViewProps {
  mode: 'add' | 'edit'
  form: LiabilityFormState
  errors: FieldErrors
  /** Top-of-form message (server text or the generic save error). */
  message: string | null
  saving: boolean
  notFound: boolean
  /** The user's `loan` / `other_liability` / `mortgage` assets (add mode picker). */
  replaceable: Asset[]
  /** The user's property assets, for a mortgage's Property select (T-12-7b). */
  properties?: Asset[]
  /** Set after a 409 `choose_commitment`: the picker step replaces the form. */
  candidates: ChooseCandidate[] | null
  choice: string | null
  linkedLabel: string | null
  stale: boolean
  onChange: (patch: Partial<LiabilityFormState>) => void
  onChoose: (choice: string) => void
  onBack: () => void
  onSubmit: () => void
  onCancel: () => void
  onDelete: () => void
  onOtherDebt: () => void
}

/** The add/edit form, as markup only (state lives in LiabilityForm). */
export function LiabilityFormView(p: LiabilityFormViewProps) {
  const mortgage = p.form.kind === 'mortgage'
  const title = p.mode === 'add'
    ? mortgage ? 'Add a mortgage' : 'Add a loan or finance'
    : mortgage ? 'Edit mortgage' : `Edit ${p.form.lender}`
  return (
    <div className="modal-backdrop">
      <div id="liability-form" className="modal-panel max-h-[90vh] overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="liability-form-title">
        <h3 id="liability-form-title" tabIndex={-1} className="text-lg font-semibold text-slate-50 mb-1 focus:outline-none">
          {p.candidates ? 'Which bill is this loan?' : title}
        </h3>
        {p.candidates ? <BillPicker {...p} candidates={p.candidates} /> : <FormBody {...p} />}
      </div>
    </div>
  )
}

function FormBody(p: LiabilityFormViewProps) {
  const disabled = p.saving || p.notFound
  const field = (name: FieldName) => ({
    id: `liability-${name.split('_').join('-')}`,
    disabled,
    'aria-invalid': p.errors[name] ? true : undefined,
    'aria-describedby': p.errors[name] ? `liability-${name.split('_').join('-')}-error` : undefined,
  })
  const decimal = { type: 'text', inputMode: 'decimal' as const, autoComplete: 'off', className: 'input' }
  return (
    <form onSubmit={(e) => { e.preventDefault(); p.onSubmit() }} noValidate>
      {p.mode === 'add' && (
        <p className="text-sm text-slate-400 mb-3">Enter what your lender&apos;s statement says. nilu works out the rest.</p>
      )}
      {p.mode === 'edit' && p.linkedLabel && (
        <p className="text-sm text-slate-400 mb-3">Linked to your bill &quot;{p.linkedLabel}&quot;.</p>
      )}
      {p.mode === 'edit' && p.stale && (
        <div className="banner-info mb-3">
          Your balance is from {dateLong(p.form.balance_as_of)}. Enter today&apos;s balance from your lender so the figures stay right.
        </div>
      )}
      {(p.notFound || p.message) && (
        <div className="banner-err mb-3" role="alert" tabIndex={-1} id="liability-errors">
          {p.notFound ? NOT_FOUND : p.message}
        </div>
      )}

      <div className="space-y-3">
        {p.mode === 'add' && p.replaceable.length > 0 && (
          <Field label="Replace an entry on your balance sheet" htmlFor="liability-replace">
            <select id="liability-replace" className="input" disabled={disabled} value={p.form.replaces_asset_id ?? ''}
              onChange={(e) => p.onChange({ replaces_asset_id: e.target.value || undefined })}>
              <option value="">None</option>
              {p.replaceable.map((a) => {
                const v = latestValue(a)
                return <option key={a.id} value={a.id}>{`${a.name} · ${v < 0 ? '−' : ''}${gbp0(Math.abs(v))}`}</option>
              })}
            </select>
          </Field>
        )}
        <Field label="Type" htmlFor="liability-kind" error={p.errors.kind}>
          <select {...field('kind')} className="input" value={p.form.kind}
            onChange={(e) => p.onChange(kindChange(e.target.value as Liability['kind'], p.form.property_asset_id ?? '', p.properties ?? []))}>
            {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </Field>
        {p.form.kind === 'mortgage' && (
          <Field label="Property" htmlFor="liability-property" help="Used to show your equity. It does not change your net worth.">
            <select id="liability-property" className="input" disabled={disabled} value={p.form.property_asset_id ?? ''}
              onChange={(e) => p.onChange({ property_asset_id: e.target.value })}>
              <option value="">None</option>
              {(p.properties ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Lender" htmlFor="liability-lender" error={p.errors.lender}>
          <input {...field('lender')} className="input" autoComplete="off" value={p.form.lender}
            onChange={(e) => p.onChange({ lender: e.target.value })} />
        </Field>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Balance (£)" htmlFor="liability-balance" error={p.errors.balance}>
            <input {...field('balance')} {...decimal} value={p.form.balance} onChange={(e) => p.onChange({ balance: e.target.value })} />
          </Field>
          <Field label="Balance as of" htmlFor="liability-balance-as-of" error={p.errors.balance_as_of}
            help={p.form.opted_out ? 'Because you repay irregularly, nilu shows this balance exactly as you enter it.' : 'nilu works out today\'s balance from this date and your payments.'}>
            <input {...field('balance_as_of')} type="date" className="input" value={p.form.balance_as_of}
              onChange={(e) => p.onChange({ balance_as_of: e.target.value })} />
          </Field>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="APR (%)" htmlFor="liability-apr" error={p.errors.apr} help="The yearly rate your lender quotes.">
            <input {...field('apr')} {...decimal} value={p.form.apr} onChange={(e) => p.onChange({ apr: e.target.value })} />
          </Field>
          <Field label="Payment (£)" htmlFor="liability-payment" error={p.errors.payment}
            help={p.mode === 'edit' && p.linkedLabel ? 'Changing the payment or how often also changes your bill for it.' : undefined}>
            <input {...field('payment')} {...decimal} value={p.form.payment} onChange={(e) => p.onChange({ payment: e.target.value })} />
          </Field>
        </div>
        <Field label="How often" htmlFor="liability-cadence" error={p.errors.cadence}>
          <select {...field('cadence')} className="input" value={p.form.cadence}
            onChange={(e) => p.onChange({ cadence: e.target.value as Liability['cadence'] })}>
            {CADENCES.map(([c, label]) => <option key={c} value={c}>{label}</option>)}
          </select>
        </Field>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Started on" htmlFor="liability-start-date" error={p.errors.start_date}>
            <input {...field('start_date')} type="date" className="input" value={p.form.start_date}
              onChange={(e) => p.onChange({ start_date: e.target.value })} />
          </Field>
          <Field label="Final payment (optional)" htmlFor="liability-end-date" error={p.errors.end_date}>
            <input {...field('end_date')} type="date" className="input" value={p.form.end_date}
              onChange={(e) => p.onChange({ end_date: e.target.value })} />
          </Field>
        </div>
        <div>
          <label className="flex items-center gap-3 min-h-[44px] text-sm text-slate-100" htmlFor="liability-opted-out">
            <input id="liability-opted-out" type="checkbox" disabled={disabled} checked={p.form.opted_out}
              aria-describedby="liability-opted-out-help" onChange={(e) => p.onChange({ opted_out: e.target.checked })} />
            I repay this loan irregularly
          </label>
          <p id="liability-opted-out-help" className="text-xs text-slate-400">
            nilu will not add a repeating payment to your bills or forecast.
          </p>
        </div>
        <button type="button" className="text-sm text-accent underline min-h-[44px]" onClick={p.onOtherDebt}>
          Mortgage or another debt? Add it as a balance sheet item.
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 mt-5">
        {p.mode === 'edit' && (
          <button id="liability-delete" type="button" className="btn-danger" disabled={p.saving} onClick={p.onDelete}>Delete loan</button>
        )}
        <span className="flex-1" />
        <button type="button" className="btn-ghost" onClick={p.onCancel}>Cancel</button>
        <button id="liability-save" type="submit" className="btn-primary" disabled={disabled}>
          {p.saving ? 'Saving…' : p.mode === 'add' ? 'Add loan' : 'Save'}
        </button>
      </div>
    </form>
  )
}

function BillPicker(p: LiabilityFormViewProps & { candidates: ChooseCandidate[] }) {
  return (
    <div>
      <p className="text-sm text-slate-400 mb-3">
        You already have more than one bill for {money(Number(p.form.payment))} {p.form.cadence === 'monthly' ? 'a month' : 'each time'}.
        Choose the one that pays this loan, so it only counts once.
      </p>
      {p.message && <div className="banner-err mb-3" role="alert" tabIndex={-1} id="liability-errors">{p.message}</div>}
      <fieldset className="space-y-2">
        <legend className="sr-only">Which bill is this loan?</legend>
        {p.candidates.map((c) => (
          <label key={c.id} className="flex items-start gap-3 min-h-[44px] p-2 rounded border border-white/10 text-sm">
            <input type="radio" name="liability-bill" value={c.id} checked={p.choice === c.id} onChange={() => p.onChoose(c.id)} />
            <span className="min-w-0">
              <span className="block text-slate-100">{c.label}</span>
              <span className="block text-xs text-slate-400">
                {money(Number(c.amount))} · {CADENCE_WORD[c.cadence] ?? c.cadence} · next {dateLong(c.next_date)}
              </span>
            </span>
          </label>
        ))}
        <label className="flex items-center gap-3 min-h-[44px] p-2 rounded border border-white/10 text-sm text-slate-100">
          <input type="radio" name="liability-bill" value="new" checked={p.choice === 'new'} onChange={() => p.onChoose('new')} />
          None of these. Add a new bill for this loan.
        </label>
      </fieldset>
      <div className="flex justify-end gap-2 mt-5">
        <button type="button" className="btn-ghost" onClick={p.onBack}>Back</button>
        <button type="button" className="btn-primary" disabled={!p.choice || p.saving} onClick={p.onSubmit}>
          {p.saving ? 'Saving…' : 'Add loan'}
        </button>
      </div>
    </div>
  )
}

/** Focus an element once React has rendered the state change that shows it. */
function focusSoon(id: string) {
  window.setTimeout(() => document.getElementById(id)?.focus(), 0)
}

/** Keep Tab and Shift+Tab inside the dialog (ux Accessibility). */
function trapFocus(e: KeyboardEvent) {
  const panel = document.getElementById('liability-form')
  if (!panel) return
  const items = Array.from(panel.querySelectorAll<HTMLElement>('button, input, select, [tabindex="-1"]'))
    .filter((el) => !el.hasAttribute('disabled') && el.tabIndex !== -1)
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
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

/** Add or edit a liability (ux T-10-0 B.3-B.5): owns the form state, the
 *  confirmations and the server round trips. */
export default function LiabilityForm({ liability, replaceable, properties = [], today, focusBalance = false, focusProperty = false, onClose, onSaved, onOtherDebt }: {
  liability: Liability | null
  replaceable: Asset[]
  properties?: Asset[]
  today: string
  /** Opened from the "Update balance" chip: start on Balance (ux B.3). */
  focusBalance?: boolean
  /** Opened from a mortgage's "Choose a property": start on Property. */
  focusProperty?: boolean
  onClose: () => void
  onSaved: (saved: Liability | null, toast: string) => void
  onOtherDebt: () => void
}) {
  const mode = liability ? 'edit' : 'add'
  const [form, setForm] = useState<LiabilityFormState>(() => (liability ? formFor(liability) : blankForm(today)))
  const [errors, setErrors] = useState<FieldErrors>({})
  const [message, setMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [candidates, setCandidates] = useState<ChooseCandidate[] | null>(null)
  const [choice, setChoice] = useState<string | null>(null)
  const confirm = useConfirm()
  const toast = useToast()
  const opener = useRef<Element | null>(null)

  useEffect(() => {
    opener.current = document.activeElement
    const first = focusBalance ? FOCUS.balance : focusProperty ? 'liability-property'
      : replaceable.length && !liability ? 'liability-replace' : 'liability-kind'
    document.getElementById(first)?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (document.querySelector('[role="alertdialog"]')) return  // a confirm is the top layer
      if (e.key === 'Escape') onClose()
      if (e.key === 'Tab') trapFocus(e)
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      // Back to the opener, or, when it has gone (the chooser closed, the
      // row was deleted), to the page's Add button (ux on #190).
      const back = opener.current as HTMLElement | null
      if (back && document.contains(back)) back.focus()
      else document.getElementById(FOCUS.pageAdd)?.focus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submit = async () => {
    if (saving) return  // a second press while saving sends nothing (L-15)
    if (liability && liability.linked_commitment && form.opted_out && !liability.opted_out) {
      if (!(await confirm(optOutConfirm(liability)))) {
        setForm({ ...form, opted_out: false })
        focusSoon(FOCUS.save)
        return
      }
    }
    const asset = !liability && form.replaces_asset_id ? replaceable.find((a) => a.id === form.replaces_asset_id) : undefined
    if (asset && !(await confirm(replaceConfirm(asset)))) return
    setSaving(true)
    const out = await saveLiability(liabilitiesAPI, form, liability?.id ?? null, candidates && choice ? { commitmentChoice: choice } : {})
    setSaving(false)
    setErrors(out.kind === 'invalid' ? out.errors : {})
    setMessage(null)
    const target = focusAfter(out.kind)
    if (target) focusSoon(target)
    if (out.kind === 'saved') onSaved(out.liability, liability ? 'Loan saved.' : addedToast(out.liability))
    else if (out.kind === 'choose') { setCandidates(out.candidates); setChoice(null) }
    else if (out.kind === 'invalid') {
      setMessage('Some details are not valid. Check the fields marked below and try again.')
    } else if (out.kind === 'message') setMessage(out.message)
    else if (out.kind === 'not_found') setNotFound(true)
    else setMessage(SAVE_ERROR)
  }

  const remove = async () => {
    if (!liability) return
    if (!(await confirm(deleteConfirm(liability)))) {
      focusSoon(FOCUS.delete)
      return
    }
    try {
      await liabilitiesAPI.remove(liability.id)
      onSaved(null, `${liability.lender} deleted.`)
    } catch {
      toast('We could not delete this loan. Nothing was changed. Try again.', { tone: 'err' })
    }
  }

  return (
    <LiabilityFormView
      mode={mode} form={form} errors={errors} message={message} saving={saving} notFound={notFound}
      replaceable={replaceable} properties={properties} candidates={candidates} choice={choice}
      linkedLabel={liability?.linked_commitment?.label ?? null} stale={!!liability?.balance_stale}
      onChange={(patch) => setForm({ ...form, ...patch })} onChoose={setChoice}
      onBack={() => { setCandidates(null); focusSoon(FOCUS.lender) }} onSubmit={submit} onCancel={onClose} onDelete={remove} onOtherDebt={onOtherDebt}
    />
  )
}
