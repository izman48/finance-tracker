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
