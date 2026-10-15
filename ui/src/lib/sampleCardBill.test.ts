import { describe, expect, it } from 'vitest'
import { sampleResponse } from './sampleAccount'

const get = <T,>(path: string) => sampleResponse(`/api/v1${path}`, {}) as T


describe('demo: card bills say what they are made of, as the API does (T-12-7a part 2)', () => {
  it('each sample repayment carries projected and parts that sum to its amount', () => {
    const s = get<{ next_repayments: { amount: number; projected: boolean; parts: { amount: number }[] }[] }>('/analytics/summary')
    for (const r of s.next_repayments) {
      expect(typeof r.projected).toBe('boolean')
      if (r.parts.length) expect(r.parts.reduce((t, p) => t + Number(p.amount), 0)).toBe(r.amount)
    }
  })
})
