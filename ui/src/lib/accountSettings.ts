import type { AccountSettingUpdate } from '../services/api'

/** Fields that only mean something on a credit card. The API refuses them
 * (422) on any other role (T-10-4a), so they are left out of the request. */
const REPAYMENT_FIELDS = [
  'repayment_cadence',
  'repayment_interval_months',
  'repayment_day',
  'repayment_anchor_date',
  'repayment_strategy',
  'repayment_fixed_amount',
  'repayment_installments',
  'pay_from_account_id',
  'instalment_card',
] as const

/** The request body for saving the account settings form. */
export function settingsPayload(form: AccountSettingUpdate): AccountSettingUpdate {
  const payload: AccountSettingUpdate = { ...form }
  if (form.role !== 'credit') {
    for (const field of REPAYMENT_FIELDS) delete payload[field]
    return payload
  }
  if (form.repayment_strategy === 'installments') {
    // Installments step monthly from the first-payment date.
    payload.repayment_cadence = 'every_n_months'
    payload.repayment_interval_months = 1
  }
  return payload
}

export interface Option {
  value: string
  label: string
}

/** "How is it repaid?" options (ux T-10-0 A.5). Only strategies the API
 *  computes are offered (lead, Sprint 10): "Minimum" and "Percent of
 *  statement" wait. Scheduled shows only for an instalment card or a card
 *  already on it (T-10-4a); a stored percent-of-balance stays visible. */
export function strategyOptions(
  stored: string | null | undefined, instalmentCard: boolean, selected?: string | null,
): Option[] {
  const options: Option[] = [
    { value: 'statement_balance', label: 'Statement balance (default)' },
    { value: 'full_balance', label: 'Full current balance' },
    { value: 'fixed', label: 'Fixed amount' },
    { value: 'installments', label: 'Pay off in instalments (e.g. Monzo Flex)' },
  ]
  if (stored === 'minimum_percent') options.push({ value: 'minimum_percent', label: 'Percent of current balance' })
  // Also while selected: unticking the instalment box must not leave the
  // select showing one option while the form holds another.
  if (instalmentCard || stored === 'scheduled' || selected === 'scheduled') {
    options.push({ value: 'scheduled', label: 'Scheduled payments (set each amount and date)' })
  }
  return options
}

/** Pay day options. End of month, weekly and every few months stay only for
 *  a card already using them, or while one is the selection (a legacy value
 *  shows as end of month), so the select always shows what is saved. */
export function payDayOptions(stored: string | null | undefined, selected?: string | null): Option[] {
  const options: Option[] = [
    { value: 'card_due_date', label: 'Card due date (default)' },
    { value: 'monthly', label: 'A day of the month' },
  ]
  const kept = (value: string) => stored === value || selected === value
  if (kept('end_of_month')) options.push({ value: 'end_of_month', label: 'End of month' })
  if (kept('weekly')) options.push({ value: 'weekly', label: 'Every week' })
  if (kept('every_n_months')) options.push({ value: 'every_n_months', label: 'Every few months' })
  return options
}

const STRATEGIES = ['full_balance', 'fixed', 'installments', 'minimum_percent', 'scheduled', 'statement_balance']
const CADENCES = ['monthly', 'end_of_month', 'every_n_months', 'weekly', 'card_due_date']

/** A card with nothing stored starts on statement balance and the card due
 *  date (ux A10, C-13). A legacy free-text value shows as what the forecast
 *  computes for it (T-10-4a: full balance, month-end), so the form saves what
 *  it shows. Nothing is written until the user saves. */
export function initialRepayment(account: {
  repayment_strategy: string | null
  repayment_cadence: string | null
  instalment_card?: boolean
}): Pick<AccountSettingUpdate, 'repayment_strategy' | 'repayment_cadence' | 'instalment_card'> {
  const strategy = account.repayment_strategy
  const cadence = account.repayment_cadence
  return {
    repayment_strategy: strategy == null ? 'statement_balance' : STRATEGIES.includes(strategy) ? strategy : 'full_balance',
    repayment_cadence: cadence == null ? 'card_due_date' : CADENCES.includes(cadence) ? cadence : 'end_of_month',
    instalment_card: account.instalment_card ?? false,
  }
}

/** An amount field's text as the API wants it: a decimal string (never a
 *  JSON float), or null when blank. */
export function amountInput(text: string): string | null {
  return text.trim() === '' ? null : text.trim()
}

const DAY_ERROR = 'Enter a day from 1 to 31.'

/** Checks before saving (C-15). */
export function validateRepayment(form: AccountSettingUpdate): { repayment_day?: string } {
  if (form.role !== 'credit' || form.repayment_cadence !== 'monthly') return {}
  const day = form.repayment_day
  return Number.isInteger(day) && day! >= 1 && day! <= 31 ? {} : { repayment_day: DAY_ERROR }
}

const SAVE_ERROR = 'We could not save these settings. Nothing was changed. Check your connection and try again.'
const SCHEDULED_ERROR =
  'Scheduled payments are only for instalment cards. Tick "This is an instalment card" to use them, or choose another option.'

/** What a failed save says (ux A.6): the API refuses a switch to scheduled
 *  on a standard card with 422. */
export function saveErrorMessage(error: unknown, strategy: string | null | undefined): string {
  const status = (error as { response?: { status?: number } })?.response?.status
  return status === 422 && strategy === 'scheduled' ? SCHEDULED_ERROR : SAVE_ERROR
}
