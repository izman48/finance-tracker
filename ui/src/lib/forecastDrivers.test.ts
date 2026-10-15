import { describe, expect, it } from 'vitest'
import { forecastDrivers } from './forecastDrivers'
import type { ContributionBasis, Projection } from '../services/api'

// What moves net worth each month in the forecast (owner 2026-10-15: "where
// do budgets and commitments show in the forecast?"). Every figure is one the
// API returned; the total is their sum.
const basis = (over: Partial<ContributionBasis> = {}): ContributionBasis => ({
  income_monthly: '3200.00', bills_monthly: '818.19', avg_spending_monthly: '2900.00',
  contribution: '931.81', spending_months_sampled: 6, spending_subtracted: true,
  spending_applied: '1450.00', spending_source: 'measured', spending_choice: 'budgets',
  spending_used: 'budgets', budgets_monthly: '1450.00', budgets_fallback: false, sampled_months: [],
  ...over,
})
const projection = (over: Partial<Projection> = {}): Projection => ({
  current_net_worth: '-5938.00', target_amount: '1000000', target_date: '2049-08-15',
  monthly_contribution: '931.81', contribution_basis: basis(), annual_growth_pct: '5',
  mode: 'cashflow', bank_component: '-118.00',
  asset_assumptions: [
    { name: 'InvestEngine ISA', growth_pct: '5.00', monthly_contribution: '1000.00' },
    { name: 'Old car', growth_pct: '0', monthly_contribution: '0.00' },
  ],
  as_of: '2026-10-15', timeline: [], ...over,
})

describe('forecastDrivers', () => {
  it('cashflow: income, bills and commitments, budgets; a contribution is a move, never a gain (T-12-0)', () => {
    const d = forecastDrivers(projection())
    expect(d.rows).toEqual([
      { label: 'Income', detail: 'your income commitments', amount: 3200 },
      { label: 'Bills and commitments', detail: 'confirmed bills, card repayments left out', amount: -818.19 },
      { label: 'Everyday spending', detail: 'your budgets', amount: -1450 },
      { label: 'Into InvestEngine ISA', detail: '£1,000 moved from cash (no change to net worth)', amount: 0 },
    ])
    expect(d.total).toBeCloseTo(931.81, 2)
    expect(d.growthPct).toBe(5)
  })

  it("the owner's case: £1,000 income, £400 bills, £300 budgets, £200 into the ISA -> +£300 (not +£500)", () => {
    const d = forecastDrivers(projection({
      contribution_basis: basis({ income_monthly: '1000.00', bills_monthly: '400.00', spending_applied: '300.00',
        budgets_monthly: '300.00', contributions_monthly: '200.00', contribution: '100.00' }),
      asset_assumptions: [{ name: 'Test ISA', growth_pct: '0', monthly_contribution: '200.00' }],
    }))
    expect(d.total).toBe(300)
    expect(d.rows.find((r) => r.label === 'Into Test ISA')).toEqual(
      { label: 'Into Test ISA', detail: '£200 moved from cash (no change to net worth)', amount: 0 })
    expect(d.rows.every((r) => !(r.label.startsWith('Into') && r.amount > 0))).toBe(true)
  })

  it('names where everyday spending came from', () => {
    const detail = (over: Partial<ContributionBasis>) =>
      forecastDrivers(projection({ contribution_basis: basis(over) })).rows.find((r) => r.label === 'Everyday spending')?.detail
    expect(detail({ spending_used: 'average', spending_months_sampled: 6 })).toBe('your average over the last 6 months')
    expect(detail({ spending_used: 'estimate' })).toBe('your estimate')
    expect(detail({ spending_used: 'average', budgets_fallback: true })).toBe('your average (no active budgets)')
  })


  it('custom: the typed monthly figure replaces income, bills and spending', () => {
    const d = forecastDrivers(projection({ mode: 'custom', contribution_basis: null, monthly_contribution: '500.00' }))
    expect(d.rows).toEqual([
      { label: 'Your monthly figure', detail: 'typed in the target form', amount: 500 },
      { label: 'Into InvestEngine ISA', detail: '£1,000 moved from cash (no change to net worth)', amount: 0 },
    ])
    expect(d.total).toBe(500)
  })

  it('the total is the sum of the rows', () => {
    const d = forecastDrivers(projection())
    expect(d.total).toBeCloseTo(d.rows.reduce((s, r) => s + r.amount, 0), 6)
  })
})
