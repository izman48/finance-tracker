/**
 * Copy for income that hasn't arrived (T-08-10, ux spec section 3). Late
 * income is shown, never counted: these strings only describe it.
 */
import { dateDayMonth, gbp } from './format'

const DAY_MS = 86_400_000

/** Whole days from the expected date (YYYY-MM-DD) to today (YYYY-MM-DD). */
export function daysLate(expected: string, today: string): number {
  return Math.round((Date.parse(today) - Date.parse(expected)) / DAY_MS)
}

/** "Expected 5 Oct · 5 days late · Not counted until it arrives." */
export function lateLine(expected: string, n: number): string {
  return `Expected ${dateDayMonth(expected)} · ${n} ${n === 1 ? 'day' : 'days'} late · Not counted until it arrives.`
}

/** The forecast card's note, or null when nothing is late. Amounts arrive as decimal strings. */
export function lateIncomeNote(items: { amount: number | string }[]): string | null {
  if (items.length === 0) return null
  const total = items.reduce((sum, it) => sum + Number(it.amount), 0)
  return items.length === 1
    ? `${gbp(total)} of expected income is late and isn't counted in this forecast.`
    : `${gbp(total)} of expected income is late (${items.length} payments) and isn't counted in this forecast.`
}

/** How an amount reads: income not yet arrived is not money you have, so grey and no "+". */
export function moneyStyle(income: boolean, notArrived: boolean): { sign: string; tone: string } {
  if (income && notArrived) return { sign: '', tone: 'text-slate-400' }
  return income ? { sign: '+', tone: 'text-pos' } : { sign: '', tone: 'text-slate-100' }
}

/** "Due 5 Oct · 5 days overdue": an unpaid planned expense, which still counts (ux spec 3a). */
export function overdueLine(due: string, n: number): string {
  return `Due ${dateDayMonth(due)} · ${n} ${n === 1 ? 'day' : 'days'} overdue`
}
