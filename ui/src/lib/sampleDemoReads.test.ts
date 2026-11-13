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
  it("Claude's changes: the sample's two paid-back marks, and nothing else (T-16-1, T-03-6 AC-33)", () => {
    const audit = get('/audit') as { items: { tool: string }[]; next_cursor: null }
    expect(audit.items.map((i) => i.tool)).toEqual(['mark_paid_back', 'mark_paid_back'])
    expect(audit.next_cursor).toBeNull()
  })
})

// T-24-6: Cashflow > Plan in demo mode, by the contract's invariants.
describe('demo Plan', () => {
  const plan = get<import('./plan').PlanResponse>('/plan')
  const n = (v: string) => Math.round(Number(v) * 100)
  const sum = (xs: string[]) => xs.reduce((t, x) => t + n(x), 0)

  it('the lines add up to the penny', () => {
    expect(n(plan.not_planned)).toBe(n(plan.income.total) - n(plan.fixed.total) - n(plan.budgets.limits_total))
    expect(n(plan.fixed.total)).toBe(n(plan.fixed.paid) + n(plan.fixed.to_pay))
    expect(n(plan.fixed.total)).toBe(sum(plan.fixed.groups.map((g) => g.total)))
    expect(n(plan.income.total)).toBe(sum(plan.income.items.map((i) => i.amount)))
    expect(n(plan.outside_vs_not_planned)).toBe(n(plan.spent_outside_budgets) - n(plan.not_planned))
  })

  it("budgets match the sample's Budgets tab (unpaused), and outside spending is its other_spending", () => {
    const list = get<{ budgets: { category: string; limit_pounds: number; spent: string; paused: boolean }[]; other_spending: string }>('/budgets')
    const active = list.budgets.filter((b) => !b.paused)
    expect(plan.budgets.items.map((b) => [b.category, n(b.limit), b.spent])).toEqual(active.map((b) => [b.category, b.limit_pounds * 100, b.spent]))
    expect(n(plan.budgets.spent)).toBe(sum(plan.budgets.items.map((b) => b.spent)))
    expect(plan.spent_outside_budgets).toBe(list.other_spending)
  })

  it('income and commitments are the sample commitments, each in one place, paid ones linked to sample transactions', () => {
    const ids = new Set(get<{ items: { id: string }[] }>('/banking/transactions?page_size=1000').items.map((t) => t.id))
    const fixed = plan.fixed.groups.flatMap((g) => g.items)
    const inBudgets = plan.budgets.items.flatMap((b) => b.commitments.map((c) => c.commitment_id))
    expect(fixed.filter((c) => inBudgets.includes(c.commitment_id))).toEqual([])
    const linked = [...fixed, ...plan.income.items].filter((i) => i.status === 'paid' || i.status === 'received')
    expect(linked.length).toBeGreaterThan(0)
    for (const i of linked) expect(ids.has(i.transaction_id as string)).toBe(true)
  })
})
