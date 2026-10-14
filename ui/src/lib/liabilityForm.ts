/** The loan / finance form on Wealth (ux T-10-0 B.3-B.5; T-10-10b): form
 *  state, the format checks the browser does, the request body, what each
 *  server answer means, and the confirmation copy. Every amount shown is the
 *  API's, only formatted; money is sent as the strings typed. */
import type { Asset, Liability, LiabilityBody, ChooseCandidate } from '../services/api'
import { gbp0, money } from './format'
import { latestValue } from './assets'

export interface LiabilityFormState {
  kind: Liability['kind']
  lender: string
  balance: string
  balance_as_of: string
  apr: string
  payment: string
  cadence: Liability['cadence']
  start_date: string
  end_date: string
  opted_out: boolean
  /** A `loan` / `other_liability` asset the picker returned (add only). */
  replaces_asset_id?: string
}

export type FieldName = 'kind' | 'lender' | 'balance' | 'balance_as_of' | 'apr' | 'payment' | 'cadence' | 'start_date' | 'end_date'
export type FieldErrors = Partial<Record<FieldName, string>>

export const FIELD_ERROR: Record<FieldName, string> = {
  kind: 'Choose a type.',
  lender: "Enter the lender's name (up to 100 characters).",
  balance: 'Enter an amount above £0 and up to £1,000,000, like 9000.00.',
  balance_as_of: "The date can't be in the future.",
  apr: "Enter a number from 0 to 100. Use the APR on your lender's statement.",
  payment: 'Enter the payment amount, or tick "I repay this loan irregularly".',
  cadence: 'Choose how often you pay.',
  start_date: 'Enter the date your payments started. It sets your payment day.',
  end_date: 'The final payment must be after the start date.',
}

export const SAVE_ERROR = 'We could not save this loan. Nothing was changed. Check your connection and try again.'
export const NOT_FOUND = 'We could not find this loan. Close this window and reload the page.'
const INVALID = 'Some details are not valid. Check the fields marked below and try again.'

// The API's cross-field rules (no `loc` field) and the field each is about.
const CROSS_FIELD: [string, FieldName][] = [
  ["The balance date can't be in the future", 'balance_as_of'],
  ['The start date must be within a year from today', 'start_date'],
  ['The final payment must be after the start date', 'end_date'],
  ['Enter the payment amount, or tick', 'payment'],
]

export function blankForm(today: string): LiabilityFormState {
  return {
    kind: 'loan', lender: '', balance: '', balance_as_of: today, apr: '', payment: '', cadence: 'monthly',
    start_date: '', end_date: '', opted_out: false,
  }
}

/** The edit form, from the stored terms. */
export function formFor(l: Liability): LiabilityFormState {
  return {
    kind: l.kind, lender: l.lender, balance: l.balance, balance_as_of: l.balance_as_of, apr: l.apr,
    payment: l.payment ?? '', cadence: l.cadence, start_date: l.start_date, end_date: l.end_date ?? '',
    opted_out: l.opted_out,
  }
}

// Up to 2 decimals (eng-a nit on #190): saves a round trip for "9000.005".
const NUMBER = /^\d+(\.\d{1,2})?$/
const DATE = /^\d{4}-\d{2}-\d{2}$/

/** Only required, number and date format (ux B.3): every other rule is the
 *  server's, so the two can never disagree. */
export function checkFormat(form: LiabilityFormState): FieldErrors {
  const errors: FieldErrors = {}
  if (!form.lender.trim()) errors.lender = FIELD_ERROR.lender
  if (!NUMBER.test(form.balance.trim())) errors.balance = FIELD_ERROR.balance
  if (!DATE.test(form.balance_as_of)) errors.balance_as_of = FIELD_ERROR.balance_as_of
  if (!NUMBER.test(form.apr.trim())) errors.apr = FIELD_ERROR.apr
  if (!form.opted_out && !NUMBER.test(form.payment.trim())) errors.payment = FIELD_ERROR.payment
  if (!DATE.test(form.start_date)) errors.start_date = FIELD_ERROR.start_date
  if (form.end_date && !DATE.test(form.end_date)) errors.end_date = FIELD_ERROR.end_date
  return errors
}

/** Every term, every time; money and APR as the strings typed. */
export function liabilityBody(form: LiabilityFormState): LiabilityBody {
  const payment = form.payment.trim()
  return {
    kind: form.kind, lender: form.lender.trim(), balance: form.balance.trim(), balance_as_of: form.balance_as_of,
    apr: form.apr.trim(), payment: payment === '' ? null : payment, cadence: form.cadence,
    start_date: form.start_date, end_date: form.end_date || null, opted_out: form.opted_out,
  }
}

export interface LiabilityClient {
  create: (body: LiabilityBody) => Promise<{ data: Liability }>
  update: (id: string, body: LiabilityBody) => Promise<{ data: Liability }>
  remove: (id: string) => Promise<unknown>
}

export type SaveOutcome =
  | { kind: 'saved'; liability: Liability }
  | { kind: 'invalid'; errors: FieldErrors }
  | { kind: 'choose'; candidates: ChooseCandidate[] }
  | { kind: 'message'; message: string }
  | { kind: 'not_found' }
  | { kind: 'error' }

type ServerError = { response?: { status?: number; data?: { detail?: unknown } } }

/** Add (no id) or edit. Nothing is sent while the format checks fail. */
export async function saveLiability(
  client: LiabilityClient, form: LiabilityFormState, id: string | null,
  options: { commitmentChoice?: string } = {},
): Promise<SaveOutcome> {
  const errors = checkFormat(form)
  if (Object.keys(errors).length) return { kind: 'invalid', errors }
  const body: LiabilityBody = { ...liabilityBody(form) }
  if (options.commitmentChoice) body.commitment_choice = options.commitmentChoice
  if (!id && form.replaces_asset_id) body.replaces_asset_id = form.replaces_asset_id
  try {
    const res = id ? await client.update(id, body) : await client.create(body)
    return { kind: 'saved', liability: res.data }
  } catch (e) {
    return outcomeOf(e as ServerError)
  }
}

function outcomeOf(e: ServerError): SaveOutcome {
  const status = e.response?.status
  const detail = e.response?.data?.detail
  if (status === 404) return { kind: 'not_found' }
  if (status === 409 && isChoose(detail)) return { kind: 'choose', candidates: detail.candidates }
  if ((status === 409 || status === 422) && typeof detail === 'string') return { kind: 'message', message: detail }
  if (status === 422 && Array.isArray(detail)) {
    const errors: FieldErrors = {}
    let unplaced: string | null = null
    for (const item of detail as { loc?: unknown[]; msg?: unknown }[]) {
      const field = item.loc?.[1]
      if (typeof field === 'string' && field in FIELD_ERROR) {
        errors[field as FieldName] = FIELD_ERROR[field as FieldName]
        continue
      }
      // A cross-field rule (loc []): our API's own fixed copy, shown as text
      // under the field it is about, or in the summary (eng-a on #190).
      const msg = typeof item.msg === 'string' ? item.msg.replace(/^Value error, /, '') : ''
      const about = CROSS_FIELD.find(([start]) => msg.startsWith(start))
      if (about) errors[about[1]] = `${msg}.`
      else if (msg) unplaced = unplaced ?? msg
    }
    if (unplaced) return { kind: 'message', message: unplaced }
    return Object.keys(errors).length ? { kind: 'invalid', errors } : { kind: 'message', message: INVALID }
  }
  return { kind: 'error' }
}

function isChoose(detail: unknown): detail is { code: 'choose_commitment'; candidates: ChooseCandidate[] } {
  return typeof detail === 'object' && detail !== null && (detail as { code?: unknown }).code === 'choose_commitment'
}

const payment = (l: Liability) => (l.payment ? money(Number(l.payment)) : '')
const PER: Record<Liability['cadence'], string> = {
  monthly: 'a month', weekly: 'a week', fortnightly: 'every 2 weeks', four_weekly: 'every 4 weeks',
}
const PERIODIC: Record<Liability['cadence'], string> = {
  monthly: 'monthly', weekly: 'weekly', fortnightly: 'fortnightly', four_weekly: 'four-weekly',
}

/** Toast after an add (ux B.3), by what happened to the bill. */
export function addedToast(l: Liability): string {
  if (l.link_result === 'created') return `Loan added. ${payment(l)} ${PER[l.cadence]} is now in your bills.`
  if (l.link_result === 'linked' && l.linked_commitment) {
    return `Loan added. Linked to your existing bill "${l.linked_commitment.label}".`
  }
  return 'Loan added. No repeating payment was added.'
}

export interface ConfirmCopy {
  title: string
  body: string
  confirmLabel: string
  cancelLabel: string
  danger?: boolean
}

/** Delete (L-14): says which figure changes, and that a bill stays. */
export function deleteConfirm(l: Liability): ConfirmCopy {
  const owed = `This loan stops counting as ${gbp0(Number(l.current_balance))} of debt in your net worth.`
  const bill = l.linked_commitment
    ? ` The ${payment(l)} ${PERIODIC[l.cadence]} payment stays in your bills as a normal bill, so it still comes out of your forecast.`
    : ''
  return { title: `Delete "${l.lender}"?`, body: owed + bill, confirmLabel: 'Delete loan', cancelLabel: 'Keep it', danger: true }
}

/** Ticking "irregularly" on a linked loan, on Save (L-13). */
export function optOutConfirm(l: Liability): ConfirmCopy {
  return {
    title: 'Stop the repeating payment?',
    body: `The ${payment(l)} ${PERIODIC[l.cadence]} bill for "${l.lender}" is removed, so it no longer comes out of your forecast or safe-to-spend. The balance stays at ${gbp0(Number(l.balance))} as entered.`,
    confirmLabel: 'Remove the bill', cancelLabel: 'Keep the bill', danger: true,
  }
}

/** Replacing a balance-sheet entry on Add (L-15). */
export function replaceConfirm(asset: Asset): ConfirmCopy {
  const value = latestValue(asset)
  return {
    title: `Replace "${asset.name}" with this loan?`,
    body: `The balance sheet entry "${asset.name}" (${value < 0 ? '−' : ''}${gbp0(Math.abs(value))}) is removed and this loan counts instead, so your debt is counted once.`,
    confirmLabel: 'Replace it', cancelLabel: 'Cancel',
  }
}


/** Ids the form and the page move focus to (ux Accessibility; ux on #190). */
export const FOCUS = {
  errors: 'liability-errors',
  title: 'liability-form-title',
  lender: 'liability-lender',
  balance: 'liability-balance',
  save: 'liability-save',
  delete: 'liability-delete',
  pageAdd: 'wealth-add',
} as const

/** Where focus goes after a save attempt: the top alert for any failure,
 *  the picker's heading for a choice, and nothing for a save (the page
 *  focuses the saved row once it has rendered). */
export function focusAfter(kind: SaveOutcome['kind']): string | null {
  if (kind === 'saved') return null
  return kind === 'choose' ? FOCUS.title : FOCUS.errors
}


/** Where focus goes once the list has reloaded after the form closes: the
 *  saved loan's row, or, after a delete (its row is gone), the page's Add
 *  button. */
export function focusAfterReload(saved: Liability | null): string {
  return saved ? `liability-row-${saved.id}` : FOCUS.pageAdd
}
