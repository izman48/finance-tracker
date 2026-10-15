import { describe, expect, it } from 'vitest'
import { sampleResponse } from './sampleAccount'
import type { Asset, Liability } from '../services/api'

// Demo mode's house and mortgage (T-12-7b part 2; ux T-12-1 "Demo mode"; owner
// rule: the demo moves with the feature, derived fields included). Synthetic.
const get = <T>(path: string, params: Record<string, unknown> = {}) => sampleResponse(`/api/v1${path}`, params) as T
type Summary = Record<string, any>

describe('the sample house and mortgage', () => {
  const house = () => get<Asset[]>('/assets').find((a) => a.name === 'Sample House')!
  const mortgage = () => get<Liability[]>('/liabilities').find((l) => l.kind === 'mortgage')!

  it('Sample House £250,000 shows equity £130,000 = value − mortgage, from the API fields', () => {
    const h = house()
    expect(h).toMatchObject({ asset_type: 'property', value_today: '250000.00', mortgage_owed: '120000.00', equity: '130000.00' })
    expect(Number(h.equity)).toBe(Number(h.value_today) - Number(mortgage().current_balance))
  })
  it('Sample Bank mortgage £120,000, linked to the house and to its bill', () => {
    expect(mortgage()).toMatchObject({
      lender: 'Sample Bank', current_balance: '120000.00', property_asset_id: house().id,
      linked_commitment: { label: 'Sample Bank mortgage payment' },
    })
  })
  it('its payment is a commitment that follows the mortgage, and leaves cash monthly in the forecast', () => {
    const bill = get<Record<string, any>[]>('/analytics/commitments').find((c) => c.label === 'Sample Bank mortgage payment')!
    expect(bill).toMatchObject({ amount: 780, direction: 'expense', linked_liability: true, linked_mortgage: true })
    const f = get<{ timeline: { date: string; events: { label: string; amount: number }[] }[] }>('/analytics/forecast', { horizon: '90' })
    const paid = f.timeline.flatMap((d) => d.events.filter((e) => e.label === bill.label).map((e) => [d.date, e.amount]))
    expect(paid.length).toBeGreaterThanOrEqual(2)
    expect(paid[0]).toEqual([bill.next_date, -780])
  })
  it('net worth counts the house and the mortgage once; Total owed includes the mortgage; equity is in no total', () => {
    const s = get<Summary>('/analytics/summary')
    expect(Number(s.liabilities_total)).toBeGreaterThanOrEqual(120000)
    expect(Number(s.total_owed)).toBeCloseTo(s.credit_owed + Number(s.liabilities_total), 2)
    expect(s.net_worth).toBeCloseTo(s.available_cash + s.savings_total + s.assets_total - s.credit_owed - Number(s.liabilities_total), 2)
  })
  it('the history puts the house in property, and the groups add up to net worth', () => {
    const h = get<Record<string, string>[]>('/analytics/net-worth-history', { months: 3 })
    const last = h[h.length - 1]
    expect(Number(last.property)).toBe(250000)
    expect(Number(last.cash) + Number(last.investments) + Number(last.property) - Number(last.debt)).toBeCloseTo(Number(last.net_worth), 2)
    expect(Number(last.net_worth)).toBeCloseTo(get<Summary>('/analytics/summary').net_worth, 2)
  })
})

describe('the projection counts the mortgage payment as a bill (eng-a on #243)', () => {
  it('bills_monthly is the sum of the confirmed monthly expense commitments, as the live rule', () => {
    const bills = get<{ direction: string; status: string; cadence: string; amount: number }[]>('/analytics/commitments')
      .filter((c) => c.direction === 'expense' && c.status === 'confirmed' && c.cadence === 'monthly')
    const p = get<{ contribution_basis: { bills_monthly: string } }>('/analytics/net-worth-projection', { target_amount: 100000 })
    expect(Number(p.contribution_basis.bills_monthly)).toBeCloseTo(bills.reduce((t, c) => t + c.amount, 0), 2)
  })
})
