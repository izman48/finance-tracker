import { describe, expect, it } from 'vitest'
import { sampleResponse } from './sampleAccount'

const get = <T,>(path: string, params: Record<string, unknown> = {}) => sampleResponse(`/api/v1${path}`, params) as T


describe('demo: card bills say what they are made of, as the API does (T-12-7a part 2)', () => {
  it('each sample repayment carries projected and parts that sum to its amount', () => {
    const s = get<{ next_repayments: { amount: number; projected: boolean; parts: { amount: number }[] }[] }>('/analytics/summary')
    for (const r of s.next_repayments) {
      expect(typeof r.projected).toBe('boolean')
      if (r.parts.length) expect(r.parts.reduce((t, p) => t + Number(p.amount), 0)).toBe(r.amount)
    }
  })
})

describe('demo: the sample card shows both bill states (T-12-7a part 2, lead 2026-10-15)', () => {
  type Rep = { amount: number; due_date: string; projected: boolean; parts: { kind: string; amount: number }[] }
  const s = get<{ credit_owed: number; next_repayments: Rep[]; accounts: { id: string; repayment_strategy: string | null }[] }>('/analytics/summary')

  it('a statement_balance card: the statement is a real bill, the spend since it is projected', () => {
    expect(s.accounts.find((a) => a.id === 'sa4')!.repayment_strategy).toBe('statement_balance')
    const [bill, projected] = s.next_repayments
    expect([bill.projected, bill.parts.map((p) => p.kind)]).toEqual([false, ['statement']])
    expect([projected.projected, projected.parts.map((p) => p.kind)]).toEqual([true, ['spent_since']])
    expect(projected.due_date > bill.due_date).toBe(true)
  })

  it('the two bills add up to what is owed on the card', () => {
    expect(Math.round(s.next_repayments.reduce((t, r) => t + r.amount, 0) * 100) / 100).toBe(s.credit_owed)
  })

  it('the forecast takes each on its day, the projected one marked', () => {
    const f = get<{ timeline: { date: string; events: { kind: string; amount: number; projected?: boolean }[] }[] }>('/analytics/forecast', { horizon: '90' })
    const reps = f.timeline.flatMap((p) => p.events.filter((e) => e.kind === 'repayment' && !('plan' in e)).map((e) => [p.date, -e.amount, Boolean(e.projected)]))
    expect(reps).toEqual(s.next_repayments.map((r) => [r.due_date, r.amount, r.projected]))
  })
})
