/** Card statement block: copy, form checks and the three write actions
 * (ux T-10-0 A.2-A.4; T-10-6). The browser computes no figures: every amount
 * shown comes from the API and is only formatted here. */
import { dateLong, money } from './format'
import type { CardStatement, CardStatementBody, CardStatements } from '../services/api'

export interface StatementForm {
  statement_balance: string
  statement_date: string
  due_date: string
  minimum_due: string
}

export type StatementErrors = Partial<Record<keyof StatementForm, string>>

type Confirm = (options: {
  title: string
  body?: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
}) => Promise<boolean>

/** The calls the actions need (analyticsAPI in the app, a fake in tests). */
export interface StatementClient {
  addStatement: (accountId: string, body: CardStatementBody) => Promise<unknown>
  updateStatement: (accountId: string, statementId: string, body: CardStatementBody) => Promise<unknown>
  deleteStatement: (accountId: string, statementId: string) => Promise<unknown>
  useStatement: (accountId: string, statementId: string) => Promise<unknown>
}

const pounds = (amount: string) => money(Number(amount))
const MONEY = /^\d{1,7}(\.\d{1,2})?$/
const MAX_DAYS_TO_DUE = 60

const AMOUNT_ERROR = 'Enter an amount above £0 and up to £1,000,000, like 5584.00.'
const MINIMUM_ERROR = 'Enter an amount above £0, or leave this blank.'
const FUTURE_ERROR = "The statement date can't be in the future."
const NO_STATEMENT_DATE = 'Enter the date on your statement.'
const TOO_OLD = "The statement date can't be more than 400 days ago."
const MINIMUM_OVER = "The minimum payment can't be more than the statement balance."
const MAX_AGE_DAYS = 400
const NO_DUE_DATE = 'Enter the due date on your statement.'
const DUE_ERROR = 'The due date must be on or after the statement date, and no more than 60 days after it.'

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

function amountOk(value: string): boolean {
  if (!MONEY.test(value)) return false
  const n = Number(value)
  return n > 0 && n <= 1_000_000
}

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000)
}

/** Today as the API counts it (UTC), so a date the client accepts is never
 *  refused by the API just after midnight in BST. */
export function apiToday(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10)
}

/** The same rules the API enforces (422), checked before anything is sent.
 *  `storedDate`: when editing, the 400-day rule applies only to a changed
 *  statement date, as in the API. */
export function validateStatementForm(form: StatementForm, today: string, storedDate?: string): StatementErrors {
  const errors: StatementErrors = {}
  if (!amountOk(form.statement_balance.trim())) errors.statement_balance = AMOUNT_ERROR
  if (!form.statement_date) errors.statement_date = NO_STATEMENT_DATE
  else if (form.statement_date > today) errors.statement_date = FUTURE_ERROR
  else if (form.statement_date !== storedDate && daysBetween(form.statement_date, today) > MAX_AGE_DAYS) {
    errors.statement_date = TOO_OLD
  }
  if (!form.due_date) errors.due_date = NO_DUE_DATE
  else if (form.statement_date) {
    const gap = daysBetween(form.statement_date, form.due_date)
    if (gap < 0 || gap > MAX_DAYS_TO_DUE) errors.due_date = DUE_ERROR
  }
  const minimum = form.minimum_due.trim()
  if (minimum && !amountOk(minimum)) errors.minimum_due = MINIMUM_ERROR
  else if (minimum && !errors.statement_balance && Number(minimum) > Number(form.statement_balance)) {
    errors.minimum_due = MINIMUM_OVER
  }
  return errors
}

export function errorSummary(count: number): string {
  return `Fix the ${count} field${count === 1 ? '' : 's'} below, then save again.`
}

/** Every field, every time (sec: an edit never leaves a field to be filled
 *  from another row). */
export function statementBody(form: StatementForm): CardStatementBody {
  return {
    statement_balance: form.statement_balance.trim(),
    statement_date: form.statement_date,
    due_date: form.due_date,
    minimum_due: form.minimum_due.trim() || null,
  }
}

const status = (e: unknown) => (e as { response?: { status?: number } })?.response?.status

export type SaveOutcome =
  | { kind: 'invalid'; errors: StatementErrors }
  | { kind: 'saved' }
  | { kind: 'duplicate' }
  | { kind: 'error' }

/** Add, or edit `editingId`. Nothing is sent when the form is invalid. */
export async function saveStatement(
  client: StatementClient, accountId: string, form: StatementForm, editingId: string | null, today: string,
  storedDate?: string,
): Promise<SaveOutcome> {
  const errors = validateStatementForm(form, today, storedDate)
  if (Object.keys(errors).length) return { kind: 'invalid', errors }
  try {
    const body = statementBody(form)
    if (editingId) await client.updateStatement(accountId, editingId, body)
    else await client.addStatement(accountId, body)
    return { kind: 'saved' }
  } catch (e) {
    return { kind: status(e) === 409 ? 'duplicate' : 'error' }
  }
}

/** Delete after a confirm that says which figure nilu plans instead. */
export async function removeStatement(
  client: StatementClient, confirm: Confirm, accountId: string, statementId: string,
  context: { otherStatements: boolean; currentBalance: string },
): Promise<'cancelled' | 'deleted' | 'error'> {
  const ok = await confirm({
    title: 'Delete this statement?',
    body: context.otherStatements
      ? 'nilu goes back to your previous statement.'
      : `nilu goes back to planning your full current balance of ${pounds(context.currentBalance)} for this card.`,
    confirmLabel: 'Delete statement', cancelLabel: 'Keep it', danger: true,
  })
  if (!ok) return 'cancelled'
  try {
    await client.deleteStatement(accountId, statementId)
    return 'deleted'
  } catch {
    return 'error'
  }
}

/** Use the provider's statement for the period. The API then deletes the
 *  user's own one, so the confirm names those figures (sec). */
export async function pickStatement(
  client: StatementClient, confirm: Confirm, accountId: string, providerStatementId: string,
  mine: { statement_balance: string; due_date: string }, providerName: string,
): Promise<'cancelled' | 'used' | 'error'> {
  const ok = await confirm({
    title: `Use the statement from ${providerName}?`,
    body: `Your own figures for this statement (${pounds(mine.statement_balance)}, due ${dateLong(mine.due_date)}) will be deleted.`,
    confirmLabel: 'Use this statement', cancelLabel: 'Keep mine', danger: true,
  })
  if (!ok) return 'cancelled'
  try {
    await client.useStatement(accountId, providerStatementId)
    return 'used'
  } catch {
    return 'error'
  }
}

/** The edit form for a statement. Editing a provider statement saves the
 *  user's own one for that period (the API keeps the provider row). */
export function editFormFor(statement: CardStatement): { form: StatementForm; replacingProvider: boolean } {
  return {
    form: {
      statement_balance: statement.statement_balance,
      statement_date: statement.statement_date,
      due_date: statement.due_date,
      minimum_due: statement.minimum_due ?? '',
    },
    replacingProvider: statement.source === 'provider',
  }
}

/** The user's own statement for a statement date, if there is one. */
export function manualFor(statements: CardStatement[], statementDate: string): CardStatement | undefined {
  return statements.find((s) => s.source === 'manual' && s.statement_date === statementDate)
}
