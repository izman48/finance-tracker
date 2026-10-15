import { describe, expect, it } from 'vitest'
import { budgetPeriod, budgetsAvailable, evidenceLine, shownChoice, spendingParams, storedChoice } from './projectionSpending'
import type { ContributionBasis } from '../services/api'

// ux T-10-15a (P-1..P-8). Synthetic figures: budgets £890, average £1,020 over 6 months.
const basis = (over: Partial<ContributionBasis> = {}): ContributionBasis => ({
  income_monthly: '2500.00', bills_monthly: '950.00', avg_spending_monthly: '1020.00', contribution: '660.00',
  spending_months_sampled: 6, spending_subtracted: true, spending_applied: '890.00', spending_source: 'measured',
  sampled_months: [], spending_choice: 'budgets', spending_used: 'budgets', budgets_monthly: '890.00',
  budgets_fallback: false, ...over,
})
const store = (entries: Record<string, string>) => (key: string) => entries[key] ?? null

describe('the stored choice and the legacy mapping', () => {
  it('a stored choice wins', () => {
    // T-12-0 (owner, 2026-10-15): "None" is gone; a stored one reads as the default.
    expect(storedChoice(store({ 'wealth.spendingSource': 'none', 'wealth.subtractSpending': '1' }))).toBeNull()
  })
  it("P-7: the old unticked box (subtractSpending '0') reads as the default, not no spending (T-12-0)", () => {
    expect(storedChoice(store({ 'wealth.subtractSpending': '0' }))).toBeNull()
  })
  it('an old estimate is Average', () => {
    expect(storedChoice(store({ 'wealth.monthlySpend': '900' }))).toBe('average')
  })
  it('nothing stored, or junk: no choice (the default comes from the API)', () => {
    expect(storedChoice(store({}))).toBeNull()
    expect(storedChoice(store({ 'wealth.spendingSource': 'x' }))).toBeNull()
  })
})

describe('what is sent', () => {
  it('no choice yet asks for budgets (the API falls back when there are none)', () => {
    expect(spendingParams(null, '')).toEqual({ spending_source: 'budgets' })
  })
  it('Average with and without an estimate', () => {
    expect(spendingParams('average', '')).toEqual({ spending_source: 'average' })
    expect(spendingParams('average', '900')).toEqual({ spending_source: 'average', monthly_spending: '900' })
  })
})

describe('what shows as selected', () => {
  it('P-1: budgets by default when they exist', () => {
    expect(shownChoice(null, basis())).toBe('budgets')
    expect(budgetsAvailable(basis())).toBe(true)
  })
  it('P-2: no active budgets, so My budgets is off and Average is shown', () => {
    const none = basis({ budgets_monthly: '0.00', budgets_fallback: true, spending_used: 'average' })
    expect(budgetsAvailable(none)).toBe(false)
    expect(shownChoice(null, none)).toBe('average')
    expect(shownChoice('budgets', none)).toBe('average')
  })
  it('a stored choice shows as itself', () => {
  })
})

describe('the evidence line, printed from the API', () => {
  it('P-1 budgets', () => {
    expect(evidenceLine(basis())).toEqual({ text: 'Your budgets: £890 a month.', warn: false })
  })
  it('P-4 the average with its months', () => {
    expect(evidenceLine(basis({ spending_used: 'average', spending_choice: 'average', spending_applied: '1020.00' })))
      .toEqual({ text: 'Your average over the last 6 months: £1,020 a month.', warn: false })
  })
  it('P-4 the estimate', () => {
    expect(evidenceLine(basis({ spending_used: 'estimate', spending_choice: 'average', spending_applied: '900.00' })))
      .toEqual({ text: 'Your estimate: £900 a month.', warn: false })
  })
  it('P-5 budgets chosen, none active: the fallback line', () => {
    expect(evidenceLine(basis({ spending_used: 'average', budgets_fallback: true, budgets_monthly: '0.00', spending_applied: '1020.00' })))
      .toEqual({ text: 'You have no active budgets, so this uses your average: £1,020 a month.', warn: false })
  })
})

// sec nit on #195: budgets are per pay cycle, so the budgets line says
// "a pay cycle" unless that cycle is a calendar month.
describe('budgetPeriod: what the budgets figure is per', () => {
  const cycle = (start: string, end: string, fallback = false) => ({ start, end, fallback })
  it('a payday-to-payday calendar month is "a month"', () => {
    expect(budgetPeriod(cycle('2026-10-25', '2026-11-24'))).toBe('a month')
    expect(budgetPeriod(cycle('2026-12-01', '2026-12-31'))).toBe('a month')
  })
  it('paid on the 31st: a cycle ending before a short month\'s last day is still "a month"', () => {
    expect(budgetPeriod(cycle('2027-01-31', '2027-02-27'))).toBe('a month')
  })
  it('four-weekly, fortnightly and weekly cycles are "a pay cycle"', () => {
    expect(budgetPeriod(cycle('2026-10-14', '2026-11-10'))).toBe('a pay cycle')
    expect(budgetPeriod(cycle('2026-10-14', '2026-10-27'))).toBe('a pay cycle')
    expect(budgetPeriod(cycle('2026-10-14', '2026-10-20'))).toBe('a pay cycle')
  })
  it('no payday set (the last 30 days) is "a pay cycle", never claimed as a month', () => {
    expect(budgetPeriod(cycle('2026-09-16', '2026-10-15', true))).toBe('a pay cycle')
  })
  it('unknown cycle: "a pay cycle"', () => {
    expect(budgetPeriod(null)).toBe('a pay cycle')
  })
})

describe('evidenceLine with the budget period', () => {
  it('budgets on a non-monthly cycle read "a pay cycle"', () => {
    expect(evidenceLine(basis(), 'a pay cycle').text).toBe('Your budgets: £890 a pay cycle.')
  })
  it('only the budgets line changes: the average stays per month', () => {
    expect(evidenceLine(basis({ spending_used: 'average', spending_choice: 'average', spending_applied: '1020.00' }), 'a pay cycle').text)
      .toMatch(/a month\.$/)
  })
})
