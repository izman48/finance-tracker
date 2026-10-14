/** Card statement block copy (ux T-10-0 A.2; T-10-6). The browser computes
 * no figures: every amount shown comes from the API and is only formatted. */
import { dateLong, money } from './format'
import type { CardStatements } from '../services/api'

const pounds = (amount: string) => money(Number(amount))

/** "nilu will pay …" under the statement rows, or null when there is no
 *  next payment to describe (the sentence is then hidden). */
export function statementSentence(data: CardStatements): string | null {
  const current = data.current
  if (!current) return null
  const spentSince = Number(current.unbilled) > 0
    ? ` The ${pounds(current.unbilled)} spent since goes on your next bill.`
    : ''
  if (current.paid) return `This statement is paid.${spentSince}`
  const next = data.next_payment
  if (!next) return null
  const from = next.from_account_name ? ` from ${next.from_account_name}` : ''
  return `nilu will pay ${pounds(next.amount)} on ${dateLong(next.date)}${from}.${spentSince}`
}
