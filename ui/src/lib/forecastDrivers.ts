/** What moves net worth each month in the Forecast view (owner 2026-10-15).
 *
 * Only the API's own figures: the projection's contribution basis (income
 * and bill commitments, the everyday spending it subtracted). A holding's
 * monthly contribution only moves cash into it, so it shows as a move with
 * £0 in the sum (T-12-0). Growth comes on top, at the stated %. */
import type { ContributionBasis, Projection } from '../services/api'
import { gbp, gbp0 } from './format'

const pounds = (n: number) => (Number.isInteger(n) ? gbp0(n) : gbp(n))

export interface DriverRow {
  label: string
  detail: string
  /** Signed, pounds a month: money out is negative. */
  amount: number
}

export interface ForecastDrivers {
  rows: DriverRow[]
  /** The rows added up: net worth's monthly change before growth. */
  total: number
  growthPct: number
  notes: string[]
}

function spendingDetail(basis: ContributionBasis): string {
  if (basis.budgets_fallback) return 'your average (no active budgets)'
  switch (basis.spending_used) {
    case 'budgets':
      return 'your budgets'
    case 'estimate':
      return 'your estimate'
    default:
      return `your average over the last ${basis.spending_months_sampled} months`
  }
}

function cashflowRows(basis: ContributionBasis): { rows: DriverRow[]; notes: string[] } {
  const rows: DriverRow[] = [
    { label: 'Income', detail: 'your income commitments', amount: Number(basis.income_monthly) },
    { label: 'Bills and commitments', detail: 'confirmed bills, card repayments left out', amount: -Number(basis.bills_monthly) },
  ]
  rows.push({ label: 'Everyday spending', detail: spendingDetail(basis), amount: -Number(basis.spending_applied) })
  return { rows, notes: [] }
}

export function forecastDrivers(projection: Projection): ForecastDrivers {
  const basis = projection.contribution_basis
  const base = basis
    ? cashflowRows(basis)
    : {
        rows: [{ label: 'Your monthly figure', detail: 'typed in the target form', amount: Number(projection.monthly_contribution) }],
        notes: [],
      }
  // A contribution only moves cash into the holding (T-12-0, owner): shown
  // as a move with £0 in the sum, never as a gain.
  const holdings = projection.asset_assumptions
    .filter((a) => Number(a.monthly_contribution) > 0)
    .map((a) => ({
      label: `Into ${a.name}`,
      detail: `${pounds(Number(a.monthly_contribution))} moved from cash (no change to net worth)`,
      amount: 0,
    }))
  const rows = [...base.rows, ...holdings]
  return {
    rows,
    total: rows.reduce((sum, r) => sum + r.amount, 0),
    growthPct: Number(projection.annual_growth_pct),
    notes: base.notes,
  }
}
