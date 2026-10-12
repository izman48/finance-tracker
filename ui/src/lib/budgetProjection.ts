/**
 * Budgets on Cashflow (T-09-8; concept sections 12 and 12a). The forecast's
 * `budget_projection` gives the payday strip and the dotted line. Every
 * figure, the headroom and the difference between the two are the API's:
 * the UI does no money arithmetic (BC4, BC12). Safe to spend, "Lowest
 * point" and the solid line never change.
 */
import { dateDayMonth } from './format'
import { money } from './budgets'

type Money = number | string

export interface BudgetProjection {
  payday: string
  scheduled_balance: Money
  stick_to_budgets_balance: Money
  current_pace_balance: Money
  /** The reconciliation line's headroom on Spending. */
  headroom: Money
  /** stick_to_budgets_balance − headroom (12a). */
  difference: Money
  /** The dotted line, to the day before payday, clipped to the chart. */
  series: { date: string; balance: Money }[]
}

/** Why there's no projection: BC2 shows nothing, BC3 asks for a payday. */
export type ProjectionReason = 'no_budgets' | 'no_payday' | null | undefined

const signed = (value: Money) => {
  const n = Number(value)
  return n < 0 ? `−${money(-n)}` : money(n)
}

export const stripTitle = (p: BudgetProjection) =>
  `Your balance on payday (${dateDayMonth(p.payday)}), before your pay arrives`

export interface StripFigure {
  label: string
  explain: string
  amount: string
  /** `text-neg` only below £0, as elsewhere. */
  negative: boolean
  /** Its swatch: the solid line, the dotted line, or none (a number only). */
  line: 'solid' | 'dotted' | 'none'
}

export function stripFigures(p: BudgetProjection): StripFigure[] {
  const figure = (label: string, explain: string, value: Money, line: StripFigure['line']): StripFigure => ({
    label, explain, amount: signed(value), negative: Number(value) < 0, line,
  })
  return [
    figure('Scheduled only', 'Bills and plans, no day-to-day spending', p.scheduled_balance, 'solid'),
    figure('If you stick to your budgets', 'Remaining budgets, other spending at your pace', p.stick_to_budgets_balance, 'dotted'),
    figure('At your current pace', 'Everything at the rate so far', p.current_pace_balance, 'none'),
  ]
}

export const STRIP_FOOTNOTE =
  'The dotted line stops at payday: your next cycle’s budgets start then. Safe to spend and “Lowest point” use the solid line only and are unchanged.'

/** BC12: said once when the two figures differ; never "wrong", never "the same". */
export function differenceSentence(p: BudgetProjection): string | null {
  const diff = Number(p.difference)
  if (diff === 0) return null
  return `Your headroom on Spending (${signed(p.headroom)}) starts from your safe to spend; this starts from your forecast balance, so they differ by ${money(Math.abs(diff))}.`
}

/** BC6: informational, only when the dotted line goes below £0. */
export function dipSentence(p: BudgetProjection): string | null {
  const dip = p.series.find((pt) => Number(pt.balance) < 0)
  if (!dip) return null
  return `If you spent every budget in full and kept your usual other spending, you would dip below £0 on ${dateDayMonth(dip.date)}.`
}

/** BC3: the line in the footnote slot when budgets exist but no payday is set. */
export function projectionNote(p: BudgetProjection | null | undefined, reason: ProjectionReason): string | null {
  if (p || reason !== 'no_payday') return null
  return 'Set your payday on Commitments to see how your budgets affect your balance.'
}

/** The chart's points with the dotted line's value where the series has one. */
export function withBudgetLine<T extends { date: string }>(timeline: T[], p: BudgetProjection | null | undefined): (T & { budget: number | null })[] | T[] {
  if (!p) return timeline
  const byDate = new Map(p.series.map((pt) => [pt.date, Number(pt.balance)]))
  return timeline.map((pt) => ({ ...pt, budget: byDate.has(pt.date) ? (byDate.get(pt.date) as number) : null }))
}
