/** A card row's second line from the API's `statement` on a summary account
 *  (ux T-10-13 "Words"; T-10-14). Shared by Wealth and Cashflow so the two
 *  say the same thing. Every amount and date is the API's, only formatted. */
import { dateDayMonth, money } from './format'

/** `statement` on a credit account: null = no statement entered; the key is
 *  absent when the response carries no statement data. */
export interface CardStatementSummary {
  statement_balance: string
  due_date: string
  paid: boolean
  /** The due date passed and no newer statement exists. */
  missing: boolean
}

export interface CardStatementLine {
  /** Line 2 text, or null when there is none. */
  text: string | null
  /** A `chip-pos` word after the text. */
  chip?: 'Paid'
  /** A separate control that opens card settings (`Add new` is styled as a chip-warn). */
  action?: 'Add statement' | 'Add new'
  /** Wealth puts "{provider} · " before the text (ux: cases 1 and 2). */
  withProvider?: boolean
}

export function cardStatementLine(statement: CardStatementSummary | null | undefined): CardStatementLine {
  if (statement === undefined) return { text: null }
  if (statement === null) return { text: null, action: 'Add statement' }
  if (statement.missing) return { text: `Statement was due ${dateDayMonth(statement.due_date)}`, action: 'Add new' }
  if (statement.paid) return { text: 'Statement paid', chip: 'Paid', withProvider: true }
  return {
    text: `Statement ${money(Number(statement.statement_balance))} · due ${dateDayMonth(statement.due_date)}`,
    withProvider: true,
  }
}
