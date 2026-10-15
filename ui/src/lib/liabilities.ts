import type { Asset, Liability } from '../services/api'
import { dateLong, gbp0 } from './format'

/** The balance-sheet group the liabilities join (ux T-10-0 B.1). */
export const LOANS_GROUP_LABEL = 'Loans and finance'

const KIND_LABEL: Record<Liability['kind'], string> = {
  loan: 'Loan',
  finance: 'Retail finance',
  bnpl: 'Buy now pay later',
  mortgage: 'Mortgage',
}

const CADENCE_WORDS: Record<Liability['cadence'], string> = {
  monthly: 'a month',
  weekly: 'a week',
  fortnightly: 'every 2 weeks',
  four_weekly: 'every 4 weeks',
}

/** "10.9%", "11%": as entered, trailing zeros trimmed. */
export function aprLabel(apr: string): string {
  return `${Number(apr).toString()}%`
}

/** Line 2 of a liability row. Every figure is the API's, only formatted. */
export function liabilityDetail(l: Liability): string {
  const head = `${KIND_LABEL[l.kind]} · ${aprLabel(l.apr)} APR`
  if (l.paid_off) return `${head} · Paid off ${dateLong(l.end_date ?? l.payoff_date)}`
  if (l.opted_out || l.payment === null) {
    return `${head} · repaid irregularly · balance as of ${dateLong(l.balance_as_of)}`
  }
  const parts = [head, `${gbp0(Number(l.payment))} ${CADENCE_WORDS[l.cadence]}`]
  const final = l.end_date ?? l.payoff_date
  if (final) parts.push(`final payment ${dateLong(final)}`)
  if (l.interest_remaining !== null) parts.push(`interest left ${gbp0(Number(l.interest_remaining))}`)
  return parts.join(' · ')
}

/** Asset types that may be the same debt as a liability (A8, sec): a loan,
 *  mortgage (T-12-6) or other debt typed in as a balance-sheet item. */
export const REPLACEABLE_ASSET_TYPES = new Set(['loan', 'other_liability', 'mortgage'])

/** Show the "both counted" notice: both kinds of entry exist, and both count. */
export function bothCounted(assets: Asset[], liabilities: Liability[]): boolean {
  return liabilities.length > 0 && assets.some((a) => REPLACEABLE_ASSET_TYPES.has(a.asset_type))
}

const LINKED_CODES = new Set(['linked_to_liability', 'linked_to_holding'])

/** The API's message when a bill that carries a loan's repayment or an
 *  investment's contribution is edited, skipped or dismissed outside it
 *  (409 `linked_to_liability` / `linked_to_holding`), or null for any other
 *  failure. The browser shows the API's words and adds none. */
export function linkedEditMessage(error: unknown): string | null {
  const res = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  const detail = res?.data?.detail as { code?: unknown; message?: unknown } | undefined
  if (res?.status === 409 && LINKED_CODES.has(String(detail?.code)) && typeof detail?.message === 'string') {
    return detail.message
  }
  return null
}

/** The chip on a Commitments row whose bill follows an investment (ux T-11-2). */
export function linkedChip(c: { linked_holding?: boolean; linked_liability?: boolean; linked_mortgage?: boolean }): string | null {
  if (c.linked_holding) return 'Follows your investment'
  return c.linked_mortgage ? 'Follows your mortgage' : null
}

// --- mortgages and equity (T-12-7b part 2; ux T-12-1) ------------------------ #

/** The row's name: "{lender} mortgage" for a mortgage, else the lender. */
export const liabilityName = (l: Liability) => (l.kind === 'mortgage' ? `${l.lender} mortgage` : l.lender)

const monthYear = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })

/** A mortgage's line 2: `Mortgage · 4.5% APR · £780 a month · final payment Nov 2051 · for Sample House`. */
export function mortgageDetail(l: Liability, properties: Asset[]): string {
  if (l.paid_off || l.opted_out || l.payment === null) return liabilityDetail(l)
  const parts = [`${KIND_LABEL.mortgage} · ${aprLabel(l.apr)} APR`, `${gbp0(Number(l.payment))} ${CADENCE_WORDS[l.cadence]}`]
  const final = l.end_date ?? l.payoff_date
  if (final) parts.push(`final payment ${monthYear(final)}`)
  const property = properties.find((a) => a.id === l.property_asset_id)
  if (property) parts.push(`for ${property.name}`)
  return parts.join(' · ')
}

/** A mortgage with no property chosen: the row offers "Choose a property". */
export const needsProperty = (l: Liability) => l.kind === 'mortgage' && !l.property_asset_id

const signed0 = (n: number) => `${n < 0 ? '−' : ''}${gbp0(Math.abs(n))}`

/** A property's equity line, from the API's figures only (display only, never
 *  in a total), and its spoken form; null without a linked mortgage. */
export function equityLine(a: Asset): { text: string; label: string; figure: string } | null {
  if (a.equity == null || a.mortgage_owed == null || a.value_today == null) return null
  const [value, owed, equity] = [gbp0(Number(a.value_today)), gbp0(Number(a.mortgage_owed)), signed0(Number(a.equity))]
  return {
    text: `Value ${value} − mortgage ${owed} = equity ${equity}`,
    label: `Value ${value} minus mortgage ${owed} equals equity ${equity}`,
    figure: equity,
  }
}

// More than this many days between the final payment entered and nilu's
// payoff date gets a warning (T-12-12).
const END_DATE_SLACK_DAYS = 31

/** When nilu's schedule (the API's `payoff_date`) ends well after the final
 *  payment the user entered, the APR or payment is usually wrong (T-10-7a
 *  review, T-12-12). Text only; it changes no figure. */
export function endDateWarning(l: Liability): string | null {
  if (l.paid_off || l.opted_out || !l.end_date || !l.payoff_date) return null
  const days = (Date.parse(`${l.payoff_date}T00:00:00Z`) - Date.parse(`${l.end_date}T00:00:00Z`)) / 86_400_000
  if (days <= END_DATE_SLACK_DAYS) return null
  return `nilu works out the last payment as ${monthYear(l.payoff_date)}, after the final payment you entered ` +
    `(${monthYear(l.end_date)}). Check the APR and payment.`
}
