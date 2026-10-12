/**
 * Spending > Budgets > Past cycles (T-09-9; concept section 14, BH1-BH14).
 * GET /budgets/history returns completed cycles oldest first, with every
 * count, verdict and trend already worked out by the server; these helpers
 * only put them into words. The one sum here, `nowSpent`, sizes the hatched
 * current-cycle bar and is never shown as a figure (BH14).
 */
import { dateDayMonth, gbp0 } from './format'
import { money, type Budget } from './budgets'

type Money = number | string

export const HISTORY_PAGE = 6
export const HISTORY_MAX = 12

export interface HistoryCycle {
  start: string
  end: string
  total_limit: Money
  total_spent: Money
  /** Null when every budget was paused in it (not counted). */
  on_target: boolean | null
}

export interface HistorySlot {
  start: string
  end: string
  /** False before the budget was made: an empty slot (BH4). */
  existed: boolean
  /** A dashed "Paused" slot, not counted (BH5). */
  paused: boolean
  limit_pounds: number | null
  spent: Money | null
  kept: boolean | null
}

/** One row per category (BH15): a removed and re-added category is one row. */
export interface HistoryBudget {
  /** The current budget, or the last one if the category was removed. */
  budget_id: string
  category: string
  /** The current limit, or the last one if removed (BH15). */
  limit_pounds?: number
  /** No active budget for this category now: a "Removed" chip (BH15). */
  removed?: boolean
  kept: number
  counted: number
  usually: Money | null
  cycles: HistorySlot[]
}

export interface HistoryResponse {
  cycles: HistoryCycle[]
  budgets: HistoryBudget[]
  on_target: number
  counted: number
  trend: { difference: Money; direction: 'lower' | 'higher' | 'same' } | null
  has_more: boolean
}

const range = (start: string, end: string) => `${dateDayMonth(start)} to ${dateDayMonth(end)}`

export function headline(h: HistoryResponse): string {
  if (h.counted === 0) return 'No cycles counted yet: your budgets were paused.'
  if (h.counted === 1) return `On target in ${h.on_target} of 1 cycle so far`
  return `On target in ${h.on_target} of the last ${h.counted} cycles`
}

export function trendText(trend: HistoryResponse['trend']): string {
  if (!trend) return 'Trend appears after 6 completed cycles.'
  if (trend.direction === 'same') return 'Your budgeted spending is about the same as in the 3 cycles before.'
  return `Your budgeted spending is about ${money(trend.difference)} a cycle ${trend.direction} than in the 3 cycles before.`
}

export function cycleBarLabel(c: HistoryCycle): string {
  if (c.on_target === null) return `${range(c.start, c.end)}: all budgets paused, not counted`
  const result = c.on_target ? 'within your limits' : 'over your limits'
  return `${range(c.start, c.end)}: spent ${money(c.total_spent)} of ${money(c.total_limit)}, ${result}`
}

export function slotLabel(s: HistorySlot): string {
  if (!s.existed) return `${range(s.start, s.end)}: no budget yet`
  if (s.paused || s.spent === null || s.limit_pounds === null) return `${range(s.start, s.end)}: paused, not counted`
  const result = s.kept ? 'within your limit' : 'over your limit'
  return `${range(s.start, s.end)}: spent ${money(s.spent)} of ${money(s.limit_pounds)}, ${result}`
}

export const nowBarLabel = (cycleStart: string) => `${dateDayMonth(cycleStart)} to now: this cycle, still running, not counted`

export function keptText(b: HistoryBudget): string {
  return b.counted === 0 ? 'Paused in these cycles' : `Kept ${b.kept} of ${b.counted}`
}

/** The server's current (or last) limit and its "usually", in whole pounds (ux on #165). */
export function budgetLimitText(b: HistoryBudget): string {
  const latest = b.limit_pounds ?? [...b.cycles].reverse().find((s) => s.existed && s.limit_pounds !== null)?.limit_pounds
  const limit = latest != null ? `Limit ${money(latest)}` : ''
  return b.usually === null ? limit : `${limit} · usually ${gbp0(Number(b.usually))}`
}

/** The chart's top: the tallest bar or limit line, with a little room above. */
export const chartMax = (values: number[]) => Math.max(0, ...values) * 1.12

/** A bar's height as a percentage of the chart. */
export const barHeight = (value: number, max: number) => (max > 0 ? (Math.max(0, value) / max) * 100 : 0)

/** The current cycle's tracked spend, to size the hatched "Now" bar only. */
export const nowSpent = (budgets: Budget[]) =>
  budgets.filter((b) => !b.paused).reduce((sum, b) => sum + Number(b.spent), 0)

export const showMore = (h: HistoryResponse) => h.has_more && h.cycles.length < HISTORY_MAX
