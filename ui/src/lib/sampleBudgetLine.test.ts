import { describe, expect, it } from 'vitest'
import { sampleResponse } from './sampleAccount'
import type { BudgetsResponse } from './budgets'
import type { BudgetProjection } from './budgetProjection'

// Demo mode's Cashflow budget line and budget nudges (T-11-10; the owner's
// screenshot: "Where it's going" showed no budgets in demo). The same rule as
// the API (services/budgets.budget_projection): the scheduled line less what
// is left of this cycle's budgets, spread evenly to the day before payday,
// less the full budget total spread over each later cycle. Paused budgets
// don't count. Figures reconcile with the demo Budgets section. Synthetic.
type Forecast = { timeline: { date: string; balance: number; events: { label: string; amount: number }[] }[]; budget_projection: BudgetProjection | null; budget_projection_reason: string | null }
const forecast = (horizon: string) => sampleResponse('/api/v1/analytics/forecast', { horizon }) as Forecast
const budgets = () => sampleResponse('/api/v1/budgets', {}) as BudgetsResponse
const n = (v: unknown) => Number(v)
const day = 86400000
const daysFrom = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / day)

// This cycle, per unpaused budget: the limit less spent and the instalments still due (T-24-3b).
const thisCycleFree = (list: BudgetsResponse) => list.budgets.filter((b) => !b.paused)
  .reduce((t, b) => t + Math.max(0, b.limit_pounds - n(b.spent) - n(b.coming_up?.amount ?? 0)), 0)
// The sample's subscriptions in a category's budget, as the demo forecast schedules them, days [from, to] ahead.
const SUBSCRIPTIONS = new Set(['Netflix', 'Spotify'])
const due = (f: Forecast, category: string, from: number, to: number) =>
  category !== 'Subscriptions' ? 0 : f.timeline.filter((_, d) => d >= from && d <= to)
    .reduce((t, p) => t + p.events.filter((e) => SUBSCRIPTIONS.has(e.label)).reduce((s, e) => s - e.amount, 0), 0)

describe.each(['payday', '30', '90', '180', '365'])('the %s forecast in demo mode', (horizon) => {
  it('has a budget line over the whole chart, starting on the solid line', () => {
    const f = forecast(horizon)
    const p = f.budget_projection!
    expect(p).not.toBeNull()
    expect(f.budget_projection_reason).toBeNull()
    expect(p.series.map((s) => s.date)).toEqual(f.timeline.map((t) => t.date))
    expect(n(p.series[0].balance)).toBeCloseTo(f.timeline[0].balance, 2)
    p.series.forEach((s, i) => expect(n(s.balance)).toBeLessThanOrEqual(f.timeline[i].balance + 0.005))
  })

  it('follows the API rule on every day, netting each budget\'s scheduled instalments (T-24-3b)', () => {
    const f = forecast(horizon)
    const list = budgets()
    const counting = list.budgets.filter((b) => !b.paused)
    const left = thisCycleFree(list)
    const eve = list.cycle.end
    const today = f.timeline[0].date
    const toEve = daysFrom(today, eve)
    // Each later cycle: per budget, the limit less that cycle's instalments in its category.
    const later = (start: number) => counting.reduce((t, b) => t + Math.max(0, b.limit_pounds - due(f, b.category, start, start + 29)), 0)
    f.timeline.forEach((t, i) => {
      const d = daysFrom(today, t.date)
      let used = d === 0 ? 0 : d >= toEve ? left : (left * d) / toEve
      // Later cycles: 30 days each from payday (the sample's pay cycle).
      for (let start = toEve + 1; start <= d; start += 30) used += d >= start + 29 ? later(start) : (later(start) * (d - start + 1)) / 30
      expect(n(f.budget_projection!.series[i].balance)).toBeCloseTo(t.balance - used, 1)
    })
  })
})

describe('the payday strip', () => {
  it('reconciles with the demo Budgets section and the summary', () => {
    const f = forecast('30')
    const p = f.budget_projection!
    const list = budgets()
    const summary = sampleResponse('/api/v1/analytics/summary', {}) as { next_payday: string }
    expect(p.payday).toBe(summary.next_payday)
    const eve = f.timeline.find((t) => t.date === list.cycle.end)!
    expect(n(p.scheduled_balance)).toBeCloseTo(eve.balance, 2)
    expect(n(p.after_budgets_balance)).toBeCloseTo(eve.balance - thisCycleFree(list), 2)
  })

  it('the payday horizon ends on payday and still has the strip', () => {
    const f = forecast('payday')
    expect(f.timeline[f.timeline.length - 1].date).toBe(f.budget_projection!.payday)
  })
})

describe('budget nudges in demo mode', () => {
  it('one per unpaused budget at its limit or ahead of pace early in the cycle, with the API wording', () => {
    const list = budgets()
    const nudges = sampleResponse('/api/v1/analytics/nudges', {}) as { id: string; body: string; detail: string; rank: number }[]
    const budgetNudges = nudges.filter((x) => x.id.startsWith('budget-'))
    const early = list.cycle.days_left >= list.cycle.days_total / 2
    const due = list.budgets.filter((b) => !b.paused && (n(b.spent) >= b.limit_pounds || (b.status === 'ahead_of_pace' && early)))
    expect(due.length).toBeGreaterThan(0)
    expect(budgetNudges.map((x) => x.body.split(' ')[0])).toEqual(due.map((b) => b.category.split(' ')[0]))
    const groceries = budgetNudges.find((x) => x.body.startsWith('Groceries'))!
    expect(groceries.body).toBe(`Groceries is ahead of pace: £${n(list.budgets[0].spent).toFixed(2)} of £320 with ${list.cycle.days_left} days left.`)
    expect(groceries.detail).toMatch(/^Spent £[\d.,]+ of £320 this pay cycle, from \d{1,2} [A-Z][a-z]{2}\.$/)
    expect(groceries.rank).toBe(10)
    expect(budgetNudges.every((x) => /^budget-[0-9a-f-]{36}$/.test(x.id))).toBe(true)
  })

  it('a paused budget never nudges', () => {
    const nudges = sampleResponse('/api/v1/analytics/nudges', {}) as { body: string }[]
    expect(nudges.some((x) => x.body.startsWith('Shopping'))).toBe(false)
  })
})
