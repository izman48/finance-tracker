import { describe, expect, it } from 'vitest'
import { sampleResponse } from './sampleAccount'

// T-12-11: the reads that used to render empty or throw in demo mode.
const get = <T>(path: string) => sampleResponse(`/api/v1${path}`, {}) as T

describe('demo reads that used to be gaps', () => {
  it('sync status: each sample bank, synced recently, consent active, not stale', () => {
    const s = get<{ connections: { provider: string; stale: boolean; consent: string; last_synced_at: string }[] }>('/banking/sync-status')
    expect(s.connections.map((c) => c.provider)).toEqual(['Everly Bank', 'Acorn Bank', 'Harbor Financial'])
    expect(s.connections.every((c) => !c.stale && c.consent === 'active' && Boolean(c.last_synced_at))).toBe(true)
  })
  it("account repayments: the sample card has no scheduled repayments (a list, so settings doesn't throw)", () => {
    expect(get('/analytics/accounts/sa4/repayments')).toEqual([])
  })
  it('a shared rule pack preview shows a sample pack', () => {
    const p = get<{ name: string; rule_count: number; rules: unknown[]; already_owned: boolean }>('/rules/shared/demo-code')
    expect(p.rule_count).toBe(p.rules.length)
    expect(p.rule_count).toBeGreaterThan(0)
    expect(p.already_owned).toBe(false)
  })
})
