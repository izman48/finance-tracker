import { describe, expect, it } from 'vitest'
import { sampleResponse } from './sampleAccount'
import type { CardPlan } from '../services/api'

// Demo mode's card plan (T-12-7b; lead 2026-10-15: one unconfirmed "Laptop
// plan" on Harbor Rewards, the only state users can reach today). The demo
// moves with the feature, derived fields included: the instalment counts in
// the forecast and safe to spend, never in net worth or Total owed (D4).
const get = <T>(path: string, params: Record<string, unknown> = {}) => sampleResponse(`/api/v1${path}`, params) as T
type Summary = Record<string, any>
type Forecast = { timeline: { date: string; events: { label: string; amount: number }[] }[] }

describe('the sample card plan', () => {
  it('is one unconfirmed Laptop plan on Harbor Rewards: £100 + £5 fee', () => {
    const plans = get<CardPlan[]>('/card-plans')
    expect(plans).toHaveLength(1)
    expect(plans[0]).toMatchObject({
      card_account_id: 'sa4', card_name: 'Harbor Rewards', name: 'Laptop plan', instalment: '100.00', fee: '5.00',
      monthly_total: '105.00', in_net_worth: false, provider_confirmed: false,
    })
    expect(Number(plans[0].balance)).toBe(100 * plans[0].instalments_remaining)
  })

  it("its instalment + fee leaves on the card's next pay day on or after its date", () => {
    const f = get<Forecast>('/analytics/forecast', { horizon: '90' })
    const s = get<Summary>('/analytics/summary')
    const plan = get<CardPlan[]>('/card-plans')[0]
    // Harbor Rewards pays weekly from its first bill's day (T-12-7a demo).
    const firstPayDay = Date.parse(s.next_repayments[0].due_date)
    const days = f.timeline.filter((d) => d.events.some((e) => e.label === 'Laptop plan instalment'))
    expect(days.length).toBeGreaterThan(0)
    expect(days[0].date >= plan.next_date).toBe(true)
    for (const d of days) {
      expect(d.events.find((e) => e.label === 'Laptop plan instalment')!.amount).toBe(-105)
      expect(((Date.parse(d.date) - firstPayDay) / 86400000) % 7).toBe(0)
    }
  })

  it('it counts in safe to spend: committed before payday includes the £105', () => {
    const s = get<Summary>('/analytics/summary')
    const rentPhoneSubsGymIsa = 1100 + 20 + 12.99 + 11.99 + 32 + 400
    const cardBills = s.next_repayments.filter((r: any) => r.due_date < s.next_payday).reduce((t: number, r: any) => t + r.amount, 0)
    expect(s.committed_before_payday).toBeCloseTo(rentPhoneSubsGymIsa + cardBills + 105, 2)
    expect(s.safe_to_spend).toBeCloseTo(s.available_cash - s.committed_before_payday, 2)
  })

  it('it is never in net worth or Total owed', () => {
    const s = get<Summary>('/analytics/summary')
    expect(Number(s.total_owed)).toBeCloseTo(s.credit_owed + s.liabilities_total, 2)
  })
})
