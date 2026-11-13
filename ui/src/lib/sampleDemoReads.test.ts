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
    expect(n(plan.not_planned)).toBe(n(plan.income.total) - n(plan.fixed.total) - n(plan.budgets.planned_total))
    // Each budget carries what it counts (T-24-4c), and the rows add up to the line (ux on #297).
    for (const b of plan.budgets.items) expect(n(b.planned)).toBe(Math.max(n(b.limit), n(b.spent) + n(b.coming_up)))
    expect(n(plan.budgets.planned_total)).toBe(sum(plan.budgets.items.map((b) => b.planned)))
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
    expect(fixed.filter((c) => c.commitment_id !== null && inBudgets.includes(c.commitment_id))).toEqual([])
    const linked = [...fixed, ...plan.income.items].filter((i) => i.status === 'paid' || i.status === 'received')
    expect(linked.length).toBeGreaterThan(0)
    for (const i of linked) expect(ids.has(i.transaction_id as string)).toBe(true)
  })
})

// eng-a on #296: demo Fixed holds every money-out source the API would, for
// the demo cycle: card repayments, a planned expense, and a bill due earlier
// this cycle and not paid.
describe('demo Plan: three sources and overdue bills', () => {
  const plan = get<import('./plan').PlanResponse>('/plan')
  const forecast = get<{ timeline: { date: string; events: { kind: string; amount: number }[] }[] }>('/analytics/forecast')
  const today = forecast.timeline[0].date
  const inCycle = (d: string) => d > today && d <= plan.cycle.end
  const group = (source: string) => plan.fixed.groups.filter((g) => g.source === source).flatMap((g) => g.items)
  const pence = (xs: number[]) => Math.round(xs.reduce((t, x) => t + x, 0) * 100)

  it("card repayments are the ones the demo forecast schedules before payday", () => {
    const scheduled = forecast.timeline.filter((t) => inCycle(t.date)).flatMap((t) => t.events)
      .filter((e) => e.kind === 'repayment').map((e) => -e.amount)
    expect(scheduled.length).toBeGreaterThan(0)
    expect(pence(group('card_repayment').map((i) => Number(i.amount)))).toBe(pence(scheduled))
    expect(group('card_repayment').every((i) => i.commitment_id === null && i.status === 'due')).toBe(true)
  })

  it('a planned expense due this cycle is listed; a card-flagged one the repayments cover is not', () => {
    const labels = group('planned').map((i) => i.label)
    expect(labels).toContain('New laptop')
    expect(labels).not.toContain('Card bill')
  })

  it('the mortgage, last due 3 days ago and not paid, is still to pay', () => {
    const mortgage = group('commitment').filter((i) => i.label === 'Sample Bank mortgage payment')
    expect(mortgage.map((i) => [i.status, (i.due_date ?? "") < today])).toEqual([["due", true]])
  })
})

describe('demo Plan agrees with demo Budgets (T-24-5b)', () => {
  const plan = get<import('./plan').PlanResponse>('/plan')
  const list = get<{ budgets: { category: string; paused: boolean; coming_up: { amount: string } }[] }>('/budgets')

  it("each budget's coming up is the Budgets tab's", () => {
    const tab = Object.fromEntries(list.budgets.filter((b) => !b.paused).map((b) => [b.category, b.coming_up.amount]))
    expect(Object.fromEntries(plan.budgets.items.map((b) => [b.category, b.coming_up]))).toEqual(tab)
  })

  it('subscriptions sit under the Subscriptions budget, not in Fixed', () => {
    const subs = plan.budgets.items.find((b) => b.category === 'Subscriptions')
    expect(subs?.commitments.map((c) => c.label).sort()).toEqual(['Netflix', 'Spotify'])
    expect(plan.fixed.groups.flatMap((g) => g.items).some((i) => i.label === 'Netflix' || i.label === 'Spotify')).toBe(false)
  })
})
