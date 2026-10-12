/**
 * Spending > Budgets (T-09-6; concept doc nilu-budgets-concept.md, sections
 * 3 to 5, 9 and 15). Budgets watch purchases against a limit per pay cycle;
 * they never change safe to spend. Pure helpers, so every sentence is tested.
 *
 * The response shapes mirror T-09-2's `api/app/schemas/budgets.py` (#150).
 * Money arrives as decimal strings, limits as whole pounds. Category names
 * come from bank feeds and rules: rendered as text only.
 */
import type { ClaudeMarker } from '../types'
import { dateDayMonth, gbp, gbp0 } from './format'

export type PaceStatus = 'under_pace' | 'on_pace' | 'ahead_of_pace' | 'over'
type Money = number | string

export interface Budget {
  id: string
  category: string
  /** Whole pounds, 1 to 100,000. */
  limit_pounds: number
  paused: boolean
  created_via: 'web' | 'mcp'
  spent: Money
  /** Where even spending would be by today: the pace tick. */
  pace_spent: Money
  /** max(0, spent - limit). */
  over_by: Money
  /** Decided by the API, so pace has one definition; null while paused. */
  status: PaceStatus | null
  changed_by_claude?: ClaudeMarker | null
}

export interface BudgetCycle {
  start: string
  end: string
  days_total: number
  days_left: number
  /** True: no payday set, so the cycle is the last 30 days (section 5). */
  fallback: boolean
}

/** headroom = safe_to_spend − budgets_left − other_at_pace (the same rule as Cashflow's payday strip). */
export interface Reconciliation {
  safe_to_spend: Money
  budgets_left: Money
  other_at_pace: Money
  headroom: Money
}

export interface BudgetsResponse {
  cycle: BudgetCycle
  budgets: Budget[]
  /** Purchases in categories with no active, unpaused budget. */
  other_spending: Money
  total_spent: Money
  /** What the purchases lens leaves out, named on screen. */
  not_counted: { commitments: Money; transfers: Money; card_payoffs: Money; financed: Money }
  /** Null when there's no active budget. */
  reconciliation: Reconciliation | null
}

export interface BudgetSuggestion {
  category: string
  /** The last completed cycles, oldest first. */
  last_cycles: { start: string; end: string; spent: Money }[]
  /** Median of the last 3, rounded up to £10; null: not enough history. */
  suggested_limit: number | null
  reason?: 'not_enough_history' | null
  current_limit?: number | null
}

export interface SuggestResponse {
  suggestions: BudgetSuggestion[]
  /** Left out because their spending is mostly commitments. */
  commitment_covered: string[]
}

/** £212, or £150.40 when there are pence: figures are never rounded away. */
export function money(value: Money): string {
  const n = Number(value)
  return Number.isInteger(n) ? gbp0(n) : gbp(n)
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

export const daysLeftText = (days: number) => `${plural(days, 'day')} left`

export function cycleLabel(cycle: BudgetCycle): string {
  return `${dateDayMonth(cycle.start)} to ${dateDayMonth(cycle.end)} · ${daysLeftText(cycle.days_left)}`
}

const PACE_TEXT: Record<Exclude<PaceStatus, 'over'>, string> = {
  under_pace: 'Under pace',
  on_pace: 'On pace',
  ahead_of_pace: 'Ahead of pace',
}

/** "On pace", or "£12 over" in neutral words (section 4.3: no red, no alarm). */
export function statusText(b: Budget): string {
  if (b.status === 'over') return `${money(b.over_by)} over`
  return b.status ? PACE_TEXT[b.status] : 'Paused'
}

export function footText(b: Budget, daysLeft: number): string {
  if (b.status === 'over') return daysLeftText(daysLeft)
  return `${money(Math.max(b.limit_pounds - Number(b.spent), 0))} left · ${daysLeftText(daysLeft)}`
}

/** The meter's accessible name: the row in words, so pace isn't colour alone. */
export function meterLabel(b: Budget, daysLeft: number): string {
  const status = statusText(b)
  const pace = b.status === 'over' ? status : status.toLowerCase()
  return `${b.category}: ${money(b.spent)} of ${money(b.limit_pounds)}, ${pace}, ${daysLeftText(daysLeft)}`
}

/** Where the pace tick sits on the bar (0 to 1), from the API's pace figure. */
export function paceFraction(b: Budget): number {
  if (b.limit_pounds <= 0) return 0
  return Math.min(Math.max(Number(b.pace_spent) / b.limit_pounds, 0), 1)
}

const signed = (value: Money) => {
  const n = Number(value)
  return n < 0 ? `−${money(-n)}` : money(n)
}

/** The reconciliation line's figures, as the API sent them (section 3). */
export function reconciliationParts(r: Reconciliation | null) {
  if (!r) return null
  return {
    safe: signed(r.safe_to_spend),
    left: signed(r.budgets_left),
    other: signed(r.other_at_pace),
    headroom: signed(r.headroom),
  }
}

export function lastCyclesText(s: BudgetSuggestion): string {
  return `Last 3 cycles: ${s.last_cycles.slice(-3).map((c) => money(c.spent)).join(' · ')}`
}

export const LIMIT_ERROR = 'Enter a whole number of pounds from 1 to 100,000.'

/** null when `value` is a valid limit (BM3). */
export function limitError(value: string): string | null {
  const v = value.trim()
  if (!/^\d+$/.test(v)) return LIMIT_ERROR
  const n = Number(v)
  return n >= 1 && n <= 100_000 ? null : LIMIT_ERROR
}

/** One entry of PUT /budgets (upsert, all or nothing). */
export interface BudgetEntry {
  category: string
  limit_pounds: number
}

/** One row of the Suggest sheet, as the user edits it. */
export interface SuggestRow {
  category: string
  checked: boolean
  limit: string
  /** False: fewer than 3 completed cycles, so nothing is proposed (never invented). */
  available: boolean
}

export function suggestRows(suggestions: BudgetSuggestion[]): SuggestRow[] {
  return suggestions.map((s) => {
    const available = s.suggested_limit !== null
    return { category: s.category, checked: available, limit: available ? String(s.suggested_limit) : '', available }
  })
}

export const NOTHING_TICKED = 'Tick at least one budget to save.'

/** The budgets to save from the ticked rows, an error per bad row, or that nothing is ticked. */
export function checkRows(rows: SuggestRow[]): { errors: Record<string, string>; budgets: BudgetEntry[]; nothingTicked: boolean } {
  const errors: Record<string, string> = {}
  const budgets: BudgetEntry[] = []
  const ticked = rows.filter((r) => r.checked && r.available)
  for (const row of ticked) {
    const error = limitError(row.limit)
    if (error) errors[row.category] = error
    else budgets.push({ category: row.category, limit_pounds: Number(row.limit.trim()) })
  }
  const bad = Object.keys(errors).length > 0
  return { errors, budgets: bad ? [] : budgets, nothingTicked: ticked.length === 0 }
}

// --- Manage budgets (concept section 13; T-09-7) -----------------------------------

export function manageSubtitle(cycle: BudgetCycle): string {
  return `Pay cycle ${dateDayMonth(cycle.start)} to ${dateDayMonth(cycle.end)}. Changes apply to this cycle and the ones after.`
}

/** "Claude changed 2 budgets on 12 Oct", or null when Claude changed none. */
export function claudeFooter(budgets: Budget[]): string | null {
  const marks = budgets.map((b) => b.changed_by_claude).filter((m): m is ClaudeMarker => !!m)
  if (marks.length === 0) return null
  const latest = marks.map((m) => m.at).sort()[marks.length - 1]
  return `Claude changed ${plural(marks.length, 'budget')} on ${dateDayMonth(latest)}`
}

/** Categories Add budget can offer: the user's own, without a budget (paused included). */
export function addOptions(categories: string[], budgets: Budget[]): string[] {
  const taken = new Set(budgets.map((b) => b.category))
  return categories.filter((c) => c && c !== 'Uncategorized' && !taken.has(c)).sort((a, b) => a.localeCompare(b))
}

export const SAVE_ERROR = "Couldn't save your budgets. Nothing was changed. Try again."
export const SAVE_UNKNOWN = "Couldn't confirm that. Your budgets may have been saved; check them before you try again."
// The API's fixed words for a duplicate; matched to pick our copy, never shown.
const API_DUPLICATE = 'That category already has a budget.'

/** The message for a failed budget write: the spec's copy, chosen by status (and, for a 422, the API's fixed words). */
export function writeFailure(err: unknown, category: string): string {
  const response = (err as { response?: { status?: number; data?: { detail?: unknown } } } | null)?.response
  if (response?.status === undefined) return SAVE_UNKNOWN
  if (response.status === 422 && response.data?.detail === API_DUPLICATE) return `You already have a budget for ${category}.`
  return SAVE_ERROR
}
