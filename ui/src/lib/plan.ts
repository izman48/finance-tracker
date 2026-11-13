/**
 * Cashflow > Plan (T-25-2; the owner's approved shape in sprint-25.md).
 * Types mirror the `GET /plan` contract. Money arrives as decimal strings
 * and every total comes from the API: the UI only formats. Labels, group
 * names and categories are bank or rule text, rendered as text only.
 */
import type { PaceStatus } from './budgets'
import { dateDayMonth, gbp } from './format'

type Money = string

export interface PlanCycle { start: string; end: string; days_left: number }

export interface PlanMoneyInItem {
  label: string
  date: string
  amount: Money
  status: 'received' | 'expected'
  transaction_id: string | null
}

export interface PlanCommitmentItem {
  commitment_id: string
  label: string
  date: string
  amount: Money
  /** paid: a matched payment; coming: due today or later; not_seen: due earlier with no payment matched (still counted). */
  status: 'paid' | 'coming' | 'not_seen'
  transaction_id: string | null
}

export interface PlanCommitmentGroup {
  /** "Rent & bills", "Debt repayments", "Subscriptions", "Savings", a category's own name, or "Other". */
  name: string
  total: Money
  count: number
  paid_count: number
  items: PlanCommitmentItem[]
}

export interface PlanBudgetCommitment {
  commitment_id: string
  label: string
  date: string
  amount: Money
  status: 'paid' | 'due'
  transaction_id: string | null
}

export interface PlanBudget {
  budget_id: string
  category: string
  limit: Money
  spent: Money
  coming_up: Money
  /** max(limit, spent + coming up), from the API: what this row counts; rows sum to `planned_total`. */
  planned: Money
  status: PaceStatus | 'budget_used' | null
  over_by: Money
  commitments: PlanBudgetCommitment[]
  other_purchases: Money
}

export interface PlanResponse {
  cycle: PlanCycle
  money_in: { total: Money; items: PlanMoneyInItem[] }
  commitments: { total: Money; groups: PlanCommitmentGroup[] }
  budgets: { limits_total: Money; planned_total: Money; items: PlanBudget[] }
  /** money_in.total − commitments.total − budgets.planned_total */
  left_over: Money
}

/** £1,450.00: Plan always shows pence so the lines visibly add up. */
export const planMoney = (value: Money) => gbp(Number(value))

const has = (value: Money) => Number(value) > 0
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

export const cycleText = (c: PlanCycle) =>
  `${dateDayMonth(c.start)} – ${dateDayMonth(c.end)} · ${plural(c.days_left, 'day')} left`

export function moneyInSubline(m: PlanResponse['money_in']): string {
  const expected = m.items.filter((i) => i.status === 'expected').length
  const received = `${m.items.length - expected} received`
  return expected ? `${received} · ${expected} expected` : received
}

export function commitmentsSubline(c: PlanResponse['commitments']): string {
  const count = c.groups.reduce((t, g) => t + g.count, 0)
  const paid = c.groups.reduce((t, g) => t + g.paid_count, 0)
  return `${paid} of ${count} paid`
}

/** "Subscriptions (7)": the group and how many payments it holds. */
export const groupLabel = (g: PlanCommitmentGroup) => `${g.name} (${g.count})`

/** The row's figure is `planned_total`, so the limits are named here. */
export const budgetsSubline = (b: PlanResponse['budgets']) =>
  `${plural(b.items.length, 'limit')}, ${planMoney(b.limits_total)} in all`

const PACE: Record<string, string> = { under_pace: 'Under pace', on_pace: 'On pace', ahead_of_pace: 'Ahead of pace' }

/** "£521.70 spent of £500.00 · Over by £21.70 · £128.00 coming up" */
export function budgetLine(b: PlanBudget): string {
  const parts = [`${planMoney(b.spent)} spent of ${planMoney(b.limit)}`]
  if (b.status === 'over') parts.push(`Over by ${planMoney(b.over_by)}`)
  else if (b.status === 'budget_used') parts.push('Budget used')
  else if (b.status) parts.push(PACE[b.status])
  if (has(b.coming_up)) parts.push(`${planMoney(b.coming_up)} coming up`)
  return parts.join(' · ')
}

/** The chip on one item: "Paid 4 Nov", "Coming 21 Nov", "Not seen yet, due 1 Nov", "Received 30 Oct", "Expected 28 Nov". */
export function itemStatus(status: string, date: string): string {
  if (status === 'paid') return `Paid ${dateDayMonth(date)}`
  if (status === 'received') return `Received ${dateDayMonth(date)}`
  if (status === 'expected') return `Expected ${dateDayMonth(date)}`
  if (status === 'not_seen') return `Not seen yet, due ${dateDayMonth(date)}`
  return `Coming ${dateDayMonth(date)}`
}

/** "Includes Foodery £129.74" (T-25-3): the commitments a budget's spend
 *  counts, each with its paid payments this cycle summed. Null when none. */
export function budgetIncludes(plan: PlanResponse | null, category: string): string | null {
  const paid = plan?.budgets.items.find((b) => b.category === category)?.commitments.filter((c) => c.status === 'paid') ?? []
  const byLabel = new Map<string, number>()
  for (const c of paid) byLabel.set(c.label, (byLabel.get(c.label) ?? 0) + Number(c.amount))
  if (!byLabel.size) return null
  return `Includes ${[...byLabel].map(([label, amount]) => `${label} ${gbp(amount)}`).join(', ')}`
}

/** Plan's Subscriptions group, for a card on Budgets when no budget (paused
 *  or not) is for Subscriptions (T-25-3). Null otherwise. */
export function subscriptionsWithoutBudget(plan: PlanResponse | null, budgetCategories: string[]): PlanCommitmentGroup | null {
  if (budgetCategories.some((c) => c.trim().toLowerCase() === 'subscriptions')) return null
  return plan?.commitments.groups.find((g) => g.name === 'Subscriptions') ?? null
}
