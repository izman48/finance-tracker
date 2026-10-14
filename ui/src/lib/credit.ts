/** How a credit account's `credit_owed` reads to the user. The server
 * normalises the sign: positive = owed, negative = the card is in credit. */
import { money } from './format'
import type { SummaryAccount } from '../types'

export function creditAmount(owed: number | string | null | undefined) {
  const n = Number(owed ?? 0)
  if (n < 0) return { text: `${money(-n)} in credit`, tone: 'text-pos' }
  return { text: money(n), tone: 'text-warn' }
}

/** Credit accounts that actually owe money (an overpaid card owes nothing). */
export function cardsOwing(accounts: SummaryAccount[]) {
  return accounts.filter((a) => a.role === 'credit' && Number(a.credit_owed ?? 0) > 0)
}

/** Strategies the forecast pays without a stored pay day: statement balance
 *  defaults to the card due date, and scheduled lists its own dates. */
const NO_PAY_DAY_NEEDED = ['statement_balance', 'scheduled']

/** A card that owes money but that the forecast leaves out, because no
 *  repayment is set up: nothing stored, or a strategy that needs a pay day
 *  with none stored (`repayment_events`; owner D8, T-10-12). */
export function repaymentNotSetUp(account: SummaryAccount) {
  if (account.role !== 'credit' || Number(account.credit_owed ?? 0) <= 0) return false
  if (account.repayment_cadence) return false
  return !NO_PAY_DAY_NEEDED.includes(account.repayment_strategy ?? '')
}

export function cardsWithoutRepayment(accounts: SummaryAccount[]) {
  return accounts.filter(repaymentNotSetUp)
}

export const REPAYMENT_NOT_SET_UP = "Repayment not set up, so this card isn't in your forecast"

/** Wealth opens the card's settings from this link (`settingsAccountFor`). */
export function cardSettingsPath(accountId: string) {
  return `/networth?settings=${encodeURIComponent(accountId)}`
}

/** The account a settings link names, only if the summary already holds it. */
export function settingsAccountFor(search: string, accounts: SummaryAccount[]) {
  const id = new URLSearchParams(search).get('settings')
  return accounts.find((a) => a.id === id) ?? null
}
