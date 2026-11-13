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

// T-25-2: Cashflow > Plan in demo mode, by the contract's invariants.
describe('demo Plan', () => {
  const plan = get<import('./plan').PlanResponse>('/plan')
  const n = (v: string) => Math.round(Number(v) * 100)
  const sum = (xs: string[]) => xs.reduce((t, x) => t + n(x), 0)
  const items = plan.commitments.groups.flatMap((g) => g.items)

  it('the rows add up to the penny', () => {
    expect(n(plan.left_over)).toBe(n(plan.money_in.total) - n(plan.commitments.total) - n(plan.budgets.planned_total))
    for (const b of plan.budgets.items) expect(n(b.planned)).toBe(Math.max(n(b.limit), n(b.spent) + n(b.coming_up)))
    expect(n(plan.budgets.planned_total)).toBe(sum(plan.budgets.items.map((b) => b.planned)))
    expect(n(plan.commitments.total)).toBe(sum(plan.commitments.groups.map((g) => g.total)))
    for (const g of plan.commitments.groups) expect(n(g.total)).toBe(sum(g.items.map((i) => i.amount)))
    expect(n(plan.money_in.total)).toBe(sum(plan.money_in.items.map((i) => i.amount)))
  })

  it("budgets match the sample's Budgets tab (unpaused), coming up included", () => {
    const list = get<{ budgets: { category: string; limit_pounds: number; spent: string; paused: boolean; coming_up: { amount: string } }[] }>('/budgets')
    const active = list.budgets.filter((b) => !b.paused)
    expect(plan.budgets.items.map((b) => [b.category, n(b.limit), b.spent, b.coming_up]))
      .toEqual(active.map((b) => [b.category, b.limit_pounds * 100, b.spent, b.coming_up.amount]))
  })

  it('money in: the salary received; friends paying back and transfers are not income', () => {
    expect(plan.money_in.items.map((i) => [i.label, i.status])).toContainEqual(['Salary', 'received'])
    expect(plan.money_in.items.some((i) => /PATEL|OKAFOR|Transfer/.test(i.label))).toBe(false)
  })

  it('commitments: no card repayments or planned items; the ISA is Savings; each in one place', () => {
    const labels = items.map((i) => i.label)
    expect(labels).not.toContain('New laptop')
    expect(labels).not.toContain('Card bill')
    expect(labels.some((l) => l.includes('Harbor'))).toBe(false)
    expect(plan.commitments.groups.find((g) => g.name === 'Savings')?.items.map((i) => i.label)).toEqual(['Sample ISA contribution'])
    const inBudgets = plan.budgets.items.flatMap((b) => b.commitments.map((c) => c.commitment_id))
    expect(items.filter((c) => inBudgets.includes(c.commitment_id))).toEqual([])
  })

  it('the mortgage, last due 3 days ago and not paid, is not seen yet and still counted', () => {
    const mortgage = items.filter((i) => i.label === 'Sample Bank mortgage payment')
    expect(mortgage.map((i) => i.status)).toEqual(['not_seen'])
  })

  it('no Subscriptions budget: the subscriptions are Commitments, and Groceries includes Freshbox (T-25-3)', () => {
    expect(plan.commitments.groups.find((g) => g.name === 'Subscriptions')?.items.map((i) => i.label).sort()).toEqual(['Netflix', 'Spotify'])
    const groceries = plan.budgets.items.find((b) => b.category === 'Groceries')
    expect(groceries?.commitments.filter((c) => c.status === 'paid').map((c) => c.label)).toEqual(['Freshbox'])
  })

  it('paid items link to sample transactions', () => {
    const ids = new Set(get<{ items: { id: string }[] }>('/banking/transactions?page_size=1000').items.map((t) => t.id))
    const linked = [...items, ...plan.money_in.items].filter((i) => i.status === 'paid' || i.status === 'received')
    expect(linked.length).toBeGreaterThan(0)
    for (const i of linked) expect(ids.has(i.transaction_id as string)).toBe(true)
  })
})
