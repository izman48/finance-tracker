import type { Asset, Liability } from '../services/api'
import { dateLong, gbp0 } from './format'

/** The balance-sheet group the liabilities join (ux T-10-0 B.1). */
export const LOANS_GROUP_LABEL = 'Loans and finance'

const KIND_LABEL: Record<Liability['kind'], string> = {
  loan: 'Loan',
  finance: 'Retail finance',
  bnpl: 'Buy now pay later',
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

/** Asset types that may be the same debt as a liability (A8, sec): a loan or
 *  other debt typed in as a balance-sheet item. Mortgages aren't a kind yet. */
const REPLACEABLE_ASSET_TYPES = new Set(['loan', 'other_liability'])

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
export function linkedChip(c: { linked_holding?: boolean; linked_liability?: boolean }): string | null {
  return c.linked_holding ? 'Follows your investment' : null
}
