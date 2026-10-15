/** The Wealth projection's "Everyday spending" choice (ux T-10-15a;
 *  T-10-15b): what is stored, what is sent, what shows as selected, and the
 *  evidence line. Every figure is the API's `contribution_basis`; the browser
 *  only formats it. */
import type { ContributionBasis } from '../services/api'
import { gbp0, money } from './format'

// "None" is gone (owner, 2026-10-15, T-12-0): spending is always subtracted.
export type SpendingChoice = 'budgets' | 'average'
const CHOICES: SpendingChoice[] = ['budgets', 'average']
export const SPENDING_KEY = 'wealth.spendingSource'

/** The user's stored choice; old keys map onto it (ux): a stored estimate
 *  was Average. A stored "none" or the old unticked box reads as not chosen,
 *  so the default (budgets, then the average) applies (T-12-0). */
export function storedChoice(read: (key: string) => string | null): SpendingChoice | null {
  const stored = read(SPENDING_KEY)
  if (stored !== null) return (CHOICES as string[]).includes(stored) ? (stored as SpendingChoice) : null
  if ((read('wealth.monthlySpend') ?? '') !== '') return 'average'
  return null
}

/** Query params: no choice yet asks for budgets, and the API falls back to
 *  the average when there are none. The estimate goes only with Average. */
export function spendingParams(
  choice: SpendingChoice | null, estimate: string,
): { spending_source: SpendingChoice; monthly_spending?: string } {
  const source = choice ?? 'budgets'
  return source === 'average' && estimate.trim() !== ''
    ? { spending_source: source, monthly_spending: estimate.trim() }
    : { spending_source: source }
}

/** Active, unpaused budgets exist (My budgets can be picked). */
export function budgetsAvailable(basis: ContributionBasis | null | undefined): boolean {
  return Number(basis?.budgets_monthly ?? 0) > 0
}

/** The option shown as selected: the choice, or the default (budgets when
 *  they exist); budgets without any active ones shows as Average. */
export function shownChoice(choice: SpendingChoice | null, basis: ContributionBasis | null | undefined): SpendingChoice {
  const wanted = choice ?? 'budgets'
  return wanted === 'budgets' && basis && !budgetsAvailable(basis) ? 'average' : wanted
}

const pounds = (value: string) => {
  const n = Number(value)
  return Number.isInteger(n) ? gbp0(n) : money(n)
}

/** One line naming the source and the API's figure (ux T-10-15a table). */
export type BudgetPeriod = 'a month' | 'a pay cycle'

/** What the budgets figure is per. Budgets are per pay cycle (payday to the
 *  day before the next); only a cycle that is exactly a calendar month may be
 *  called "a month" (sec on #195). Not a figure, only the wording. */
export function budgetPeriod(cycle: { start: string; end: string; fallback: boolean } | null | undefined): BudgetPeriod {
  if (!cycle || cycle.fallback) return 'a pay cycle'
  const start = new Date(`${cycle.start}T00:00:00Z`)
  const next = new Date(`${cycle.end}T00:00:00Z`)
  next.setUTCDate(next.getUTCDate() + 1) // the next payday
  const months = (next.getUTCFullYear() - start.getUTCFullYear()) * 12 + next.getUTCMonth() - start.getUTCMonth()
  if (months !== 1) return 'a pay cycle'
  if (next.getUTCDate() === start.getUTCDate()) return 'a month'
  // Paid on the 29th-31st: a short month moves payday to its last day.
  const lastDayOfNextMonth = new Date(Date.UTC(next.getUTCFullYear(), next.getUTCMonth() + 1, 0)).getUTCDate()
  return next.getUTCDate() === lastDayOfNextMonth && start.getUTCDate() > lastDayOfNextMonth ? 'a month' : 'a pay cycle'
}

export function evidenceLine(basis: ContributionBasis, period: BudgetPeriod = 'a month'): { text: string; warn: boolean } {
  const applied = pounds(basis.spending_applied)
  if (basis.budgets_fallback) return { text: `You have no active budgets, so this uses your average: ${applied} a month.`, warn: false }
  switch (basis.spending_used) {
    case 'budgets':
      return { text: `Your budgets: ${applied} ${period}.`, warn: false }
    case 'estimate':
      return { text: `Your estimate: ${applied} a month.`, warn: false }
    default:
      return { text: `Your average over the last ${basis.spending_months_sampled} months: ${applied} a month.`, warn: false }
  }
}
