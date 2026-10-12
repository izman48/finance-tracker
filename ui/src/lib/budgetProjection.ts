/**
 * Budgets on Cashflow, the simple rule (T-09-15; owner 2026-10-12). The
 * forecast's `budget_projection` gives the dotted line: the scheduled line
 * less what is left of the budgets this cycle, spread to payday, and less
 * the full budget total each later cycle, over the whole chart. Every figure
 * is the API's: the UI does no money arithmetic. Safe to spend, "Lowest
 * point" and the solid line never change.
 */
import { dateDayMonth, gbp0 } from './format'
import { money } from './budgets'

type Money = number | string

export interface BudgetProjection {
  payday: string
  /** The solid line on the day before payday. */
  scheduled_balance: Money
  /** The dotted line on the day before payday. */
  after_budgets_balance: Money
  /** The dotted line: from today (at the solid line's value) to the end of the chart. */
  series: { date: string; balance: Money }[]
}

/** Why there's no projection: BC2 shows nothing, BC3 asks for a payday,
 *  BC8 says it couldn't be loaded. */
export type ProjectionReason = 'no_budgets' | 'no_payday' | 'unavailable' | null | undefined

const signed = (value: Money) => {
  const n = Number(value)
  return n < 0 ? `−${money(-n)}` : money(n)
}

const figure = (value: Money) => ({ amount: signed(value), negative: Number(value) < 0 })

/** The payday line's two figures, as the API sent them. */
export function paydayFigures(p: BudgetProjection) {
  return { scheduled: figure(p.scheduled_balance), afterBudgets: figure(p.after_budgets_balance) }
}

/** BC6: informational, only when the dotted line goes below £0. */
export function dipSentence(p: BudgetProjection): string | null {
  const dip = p.series.find((pt) => Number(pt.balance) < 0)
  if (!dip) return null
  return `If you spend all your budgets, you'd dip below £0 on ${dateDayMonth(dip.date)}.`
}

const pounds = (n: number) => (n < 0 ? `−${gbp0(-n)}` : gbp0(n))

/** The chart tooltip's budget line: both of the chart's values for that day. */
export const budgetTooltip = (scheduled: number, afterBudgets: number) =>
  `${pounds(scheduled)} scheduled · ${pounds(afterBudgets)} after budgets`

/** BC3: the line in the footnote slot when budgets exist but no payday is set. */
export function projectionNote(p: BudgetProjection | null | undefined, reason: ProjectionReason): string | null {
  if (p || reason !== 'no_payday') return null
  return 'Set your payday on Commitments to see your budgets on this chart.'
}

/** BC8: our own line in the legend slot when the server couldn't compute it. */
export function projectionUnavailable(reason: ProjectionReason): string | null {
  return reason === 'unavailable' ? "Couldn't load your budget line." : null
}

/** The chart's points with the dotted line's value where the series has one. */
export function withBudgetLine<T extends { date: string }>(timeline: T[], p: BudgetProjection | null | undefined): (T & { budget: number | null })[] | T[] {
  if (!p) return timeline
  const byDate = new Map(p.series.map((pt) => [pt.date, Number(pt.balance)]))
  return timeline.map((pt) => ({ ...pt, budget: byDate.has(pt.date) ? (byDate.get(pt.date) as number) : null }))
}
