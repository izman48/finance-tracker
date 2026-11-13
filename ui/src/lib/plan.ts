/**
 * Cashflow > Plan (T-24-6; spec docs nilu-s24-plan.md, "Plan section").
 * Types mirror the `GET /plan` contract (T-24-4). Money arrives as decimal
 * strings and every total comes from the API: the UI only formats. Labels
 * and categories are bank or rule text, rendered as text only.
 */
import type { PaceStatus } from './budgets'
import { dateDayMonth, gbp } from './format'

type Money = string

export interface PlanCycle { start: string; end: string; days_left: number }

export interface PlanIncomeItem {
  id: string
  label: string
  date: string
  amount: Money
  status: 'received' | 'expected'
  transaction_id: string | null
}

/** Where a Fixed line comes from (T-24-4): a commitment, a card repayment
 *  or a planned expense; only a commitment has a `commitment_id`. */
export type PlanSource = 'commitment' | 'card_repayment' | 'planned'

export interface PlanFixedItem {
  source: PlanSource
  commitment_id: string | null
  label: string
  due_date: string | null
  amount: Money
  status: 'paid' | 'due' | 'not_due_this_cycle'
  transaction_id: string | null
}

export interface PlanFixedGroup {
  source: PlanSource
  /** null: "No category" for commitments; card repayments and planned expenses have their own group. */
  category: string | null
  total: Money
  paid_count: number
  count: number
  items: PlanFixedItem[]
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
  status: PaceStatus | 'budget_used' | null
  over_by: Money
  commitments: PlanBudgetCommitment[]
  commitment_count: number
  other_purchases: Money
}

export interface PlanResponse {
  cycle: PlanCycle
  income: { total: Money; received_count: number; expected_count: number; items: PlanIncomeItem[] }
  fixed: { total: Money; paid: Money; to_pay: Money; paid_count: number; count: number; groups: PlanFixedGroup[] }
  /** `planned_total`: each budget at max(limit, spent + coming up), what Not planned takes off (sec). */
  budgets: { limits_total: Money; planned_total: Money; spent: Money; coming_up: Money; count: number; items: PlanBudget[] }
  spent_outside_budgets: Money
  not_planned: Money
  outside_vs_not_planned: Money
}

/** £1,450.00: Plan always shows pence so the lines visibly add up. */
export const planMoney = (value: Money) => gbp(Number(value))

const has = (value: Money) => Number(value) > 0

export const cycleText = (c: PlanCycle) =>
  `${dateDayMonth(c.start)} – ${dateDayMonth(c.end)} · ${c.days_left} day${c.days_left === 1 ? '' : 's'} left`

export const incomeSubline = (i: PlanResponse['income']) =>
  `${i.received_count} of ${i.received_count + i.expected_count} received`

export function fixedSubline(f: PlanResponse['fixed']): string {
  const paid = `${f.paid_count} of ${f.count} paid`
  return has(f.to_pay) ? `${paid} · ${planMoney(f.to_pay)} still to pay` : paid
}

export function budgetsSubline(b: PlanResponse['budgets']): string {
  const parts = [`${b.count} limit${b.count === 1 ? '' : 's'}`, `${planMoney(b.spent)} spent`]
  if (has(b.coming_up)) parts.push(`${planMoney(b.coming_up)} coming up`)
  return parts.join(' · ')
}

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

/** The chip on one item: "Paid 4 Nov", "Due 21 Nov", "Received", "Expected 28 Nov". */
export function itemStatus(status: string, date: string | null): string {
  if (status === 'paid') return `Paid ${dateDayMonth(date)}`
  if (status === 'due') return `Due ${dateDayMonth(date)}`
  if (status === 'received') return 'Received'
  if (status === 'expected') return `Expected ${dateDayMonth(date)}`
  return 'Next due outside this cycle'
}
