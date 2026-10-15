import { describe, expect, it } from 'vitest'
import { sampleResponse } from './sampleAccount'
import type { InvestmentGraph } from './investments'
import type { Asset } from '../services/api'

// Demo mode's investments (T-11-8; ux T-11-2 "Demo mode", D-1, D-3; sec:
// sample data reconciles and the projection matches the engine's maths).
// Everything is synthetic.
const get = <T>(path: string, params: Record<string, unknown> = {}) => sampleResponse(`/api/v1${path}`, params) as T
const assets = () => get<Asset[]>('/assets')
const graph = (params: Record<string, unknown> = {}) => get<InvestmentGraph>('/holdings/projection', { months: 120, ...params })
const n = (v: unknown) => Number(v)

/** The engine's arithmetic written out independently: effective-annual
 *  monthly rate, contribution at each month end, rounded at output. */
function engine(value: number, pct: number, contribution: number, months: number): number[] {
  const r = (1 + pct / 100) ** (1 / 12) - 1
  const out = [value]
  let v = value
  for (let m = 1; m <= months; m++) {
    v = v * (1 + r) + contribution
    out.push(v)
  }
  return out.map((x) => Math.round(x * 100) / 100)
}

describe('sample investments on Wealth (D-1)', () => {
  it('three sample holdings with their growth, and the ISA contribution as a linked bill', () => {
    const list = assets().filter((a) => ['isa', 'investment', 'pension', 'crypto'].includes(a.asset_type))
    expect(list.map((a) => [a.name, a.asset_type, a.assumed_growth_pct])).toEqual([
      ['Sample ISA', 'isa', '7'],
      ['Sample Pension', 'pension', '5'],
      ['Sample Crypto', 'crypto', '0'],
    ])
    const isa = list[0]
    expect(isa.monthly_contribution).toBeNull()
    expect(isa.linked_commitment).toMatchObject({ label: 'Sample ISA contribution', amount: '400.00', pay_from_account_id: 'sa1' })
  })

  it('names the ISA short enough that "contribution" fits a 390px row (ux, Sprint 11 follow-up)', () => {
    const bill = assets().find((a) => a.asset_type === 'isa')!.linked_commitment!
    expect(bill.label.length).toBeLessThanOrEqual(24)
  })

  it('the investments total is £43,700, the sum of the rows, and the summary agrees', () => {
    const total = assets().filter((a) => a.asset_type !== 'property').reduce((s, a) => s + n(a.valuations[a.valuations.length - 1].value), 0)
    expect(total).toBe(43700)
    expect(n(get<{ investments_total: string }>('/analytics/summary').investments_total)).toBe(43700)
  })
})

describe('the sample contribution is a bill (D-3)', () => {
  const summary = () => get<{ committed_before_payday: number; safe_to_spend: number; available_cash: number; next_payday: string; next_repayments: { amount: number; due_date: string }[] }>('/analytics/summary')

  it('Commitments lists it by name, linked to the holding', () => {
    const rows = get<{ label: string; amount: number; linked_holding?: boolean; direction: string }[]>('/analytics/commitments')
    expect(rows.find((r) => r.label === 'Sample ISA contribution')).toMatchObject({ amount: 400, direction: 'expense', linked_holding: true })
  })

  it('it is due before payday and counted once in what is committed, so safe to spend is lower by it', () => {
    const s = summary()
    const bills = get<{ label: string; amount: number; direction: string; next_date: string }[]>('/analytics/commitments')
    const contribution = bills.find((b) => b.label === 'Sample ISA contribution')!
    expect(contribution.next_date < get<{ next_payday: string }>('/analytics/summary').next_payday).toBe(true)
    // The sample's committed bills (rent, phone, subscriptions, gym), the
    // contribution, and the card repayments due before payday (as the API counts them).
    const counted = ['Rent', 'Phone', 'Netflix', 'Spotify', 'Gym', contribution.label]
    const cards = s.next_repayments.filter((r) => r.due_date < s.next_payday).reduce((t, r) => t + r.amount, 0)
    expect(s.committed_before_payday).toBeCloseTo(bills.filter((b) => counted.includes(b.label)).reduce((t, b) => t + b.amount, 0) + cards, 2)
    expect(s.safe_to_spend).toBeCloseTo(s.available_cash - s.committed_before_payday, 2)
  })

  it('the Cashflow forecast takes it on its day, named like the bill', () => {
    const f = get<{ timeline: { date: string; events: { label: string; amount: number }[] }[] }>('/analytics/forecast', { horizon: '30' })
    const hits = f.timeline.flatMap((p) => p.events.filter((e) => e.label === 'Sample ISA contribution').map((e) => [p.date, e.amount]))
    const bill = get<{ label: string; next_date: string }[]>('/analytics/commitments').find((r) => r.label === 'Sample ISA contribution')!
    expect(hits).toEqual([[bill.next_date, -400]])
  })
})

describe('the sample investment graph (engine maths)', () => {
  it('each holding follows the engine from its value today', () => {
    const g = graph()
    const isa = g.holdings.find((h) => h.name === 'Sample ISA')!
    expect(isa.forecast.map((p) => n(p.worth))).toEqual(engine(18500, 7, 400, 120))
    expect(n(isa.forecast[120].paid_in)).toBe(18500 + 400 * 120)
    const crypto = g.holdings.find((h) => h.name === 'Sample Crypto')!
    expect(new Set(crypto.forecast.map((p) => p.worth))).toEqual(new Set(['1200.00']))
  })

  it('the total is the holdings summed (within a penny each) and today is £43,700', () => {
    const g = graph()
    expect(n(g.total.value_today)).toBe(43700)
    expect(n(g.total.monthly_contribution)).toBe(400)
    g.total.forecast.forEach((p, i) => {
      const parts = g.holdings.reduce((s, h) => s + n(h.forecast[i].worth), 0)
      expect(Math.abs(n(p.worth) - parts)).toBeLessThanOrEqual(0.03)
    })
    expect(g.total.answer).toEqual({ months: 120, worth_about: String(Math.round(n(g.total.forecast[120].worth) / 1000) * 1000), paid_in: String(Math.round(n(g.total.forecast[120].paid_in) / 1000) * 1000) })
  })

  it('history is the valuations entered', () => {
    const isaAsset = assets().find((a) => a.name === 'Sample ISA')!
    const isa = graph().holdings.find((h) => h.name === 'Sample ISA')!
    expect(isa.history.map((p) => [p.date, n(p.worth)])).toEqual(isaAsset.valuations.map((v) => [v.valued_at, n(v.value)]))
  })

  it('the range and one holding narrow it', () => {
    expect(graph({ months: 240 }).total.forecast).toHaveLength(241)
    const one = graph({ holding_id: 'sas2' })
    expect(one.holdings.map((h) => h.name)).toEqual(['Sample Pension'])
    expect(graph({ holding_id: 'not-a-sample' }).holdings).toEqual([])
  })

  it('the target projection grows each holding the same way (equality, as the API)', () => {
    const p = get<{ timeline: { assets: string }[] }>('/analytics/net-worth-projection', { annual_growth_pct: '5', monthly_contribution: '0' })
    const g = graph()
    for (let m = 0; m <= 24; m++) expect(n(p.timeline[m].assets)).toBeCloseTo(n(g.total.forecast[m].worth), 1)
  })
})

describe('Include investments in demo mode', () => {
  it('history without investments drops exactly the investments; the groups add up', () => {
    const on = get<Record<string, string>[]>('/analytics/net-worth-history', { months: 3 })
    const off = get<Record<string, string>[]>('/analytics/net-worth-history', { months: 3, include_investments: 'false' })
    on.forEach((p, i) => {
      expect(n(p.net_worth) - n(off[i].net_worth)).toBeCloseTo(n(p.investments), 2)
      expect(n(p.cash) + n(p.investments) + n(p.property) - n(p.debt)).toBeCloseTo(n(p.net_worth), 2)
      expect(off[i].cash).toBe(p.cash)
      expect(off[i].debt).toBe(p.debt)
    })
  })

  it('the projection without investments starts lower by the investments', () => {
    const on = get<{ current_net_worth: string }>('/analytics/net-worth-projection', { monthly_contribution: '0' })
    const off = get<{ current_net_worth: string }>('/analytics/net-worth-projection', { monthly_contribution: '0', include_investments: 'false' })
    expect(n(on.current_net_worth) - n(off.current_net_worth)).toBe(43700)
  })
})

describe('demo projection to a far target', () => {
  it('has every month up to a target more than 10 years out, with no gap after month 120', () => {
    const p = get<{ target_date: string | null; timeline: { date: string }[] }>('/analytics/net-worth-projection', {
      target_amount: '3000000', annual_growth_pct: '5', monthly_contribution: '1000',
    })
    const months = p.timeline.map((t) => {
      const [y, m] = t.date.split('-').map(Number)
      return y * 12 + m
    })
    const toTarget = (() => {
      const [y, m] = (p.target_date ?? '').split('-').map(Number)
      return y * 12 + m - months[0]
    })()
    expect(toTarget).toBeGreaterThan(120)
    expect(months.slice(1).map((v, i) => v - months[i]).every((step) => step === 1)).toBe(true)
    expect(p.timeline).toHaveLength(toTarget + 7)
  })
})
