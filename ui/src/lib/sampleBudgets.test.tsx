import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { sampleResponse } from './sampleAccount'
import { sampleBudgetList } from './sampleBudgets'
import type { BudgetsResponse } from './budgets'
import type { HistoryResponse } from './budgetHistory'
import BudgetsView from '../components/budgets/BudgetsView'
import HistoryView from '../components/budgets/HistoryView'

// Demo mode serves budgets (T-11-8; known gap since Sprint 09): the Budgets
// section used to get {} and crash on data.budgets.filter. The sample budgets
// are computed from the sample ledger, so they reconcile with Spending.
const list = () => sampleResponse('/api/v1/budgets', {}) as BudgetsResponse
const history = () => sampleResponse('/api/v1/budgets/history', { cycles: 6 }) as HistoryResponse
// A budget counts purchases and, in its own category, paid commitments (T-24-3).
const purchases = (from: string, to: string, category: string) => {
  const res = sampleResponse('/api/v1/analytics/spending', {
    period: 'custom', frm: from, to, lens: 'purchases', exclude_commitments: false,
  }) as { by_category: { category: string; total: string }[] }
  return Number(res.by_category.find((c) => c.category === category)?.total ?? 0)
}
const n = (v: unknown) => Number(v)
const noop = () => {}

describe('sample budgets (this cycle)', () => {
  it('renders the Budgets view without crashing', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <BudgetsView status="ready" data={list()} onRetry={noop} onSuggest={noop} onOpenCategory={noop} />
      </MemoryRouter>,
    )
    expect(html).toContain('Groceries')
  })

  it('each budget has spent what the sample ledger shows for its category this cycle', () => {
    const data = list()
    expect(data.budgets.length).toBeGreaterThan(2)
    for (const b of data.budgets) {
      expect(n(b.spent)).toBeCloseTo(purchases(data.cycle.start, isoToday(), b.category), 2)
    }
  })

  it('the cycle runs from the sample payday for 30 days', () => {
    const { cycle } = list()
    expect(cycle.days_total).toBe(30)
    expect(cycle.fallback).toBe(false)
    expect(daysBetween(cycle.start, cycle.end)).toBe(29)
    expect(cycle.days_left).toBe(daysBetween(isoToday(), cycle.end))
  })

  it('pace, over and status follow the API rules', () => {
    const data = list()
    const elapsed = daysBetween(data.cycle.start, isoToday()) + 1
    for (const b of data.budgets) {
      const pace = Math.round(b.limit_pounds * (elapsed / data.cycle.days_total) * 100) / 100
      expect(n(b.pace_spent)).toBeCloseTo(pace, 2)
      expect(n(b.over_by)).toBeCloseTo(Math.max(0, n(b.spent) - b.limit_pounds), 2)
      if (b.paused) expect(b.status).toBeNull()
      else expect(b.status).toBe(expectedStatus(n(b.spent), n(b.pace_spent), b.limit_pounds))
    }
  })

  it('the cycle summary adds up over active, unpaused budgets; other spending makes up the total', () => {
    const data = list()
    const counting = data.budgets.filter((b) => !b.paused)
    const s = data.summary_this_cycle!
    expect(n(s.total_limit)).toBe(counting.reduce((t, b) => t + b.limit_pounds, 0))
    expect(n(s.spent)).toBeCloseTo(counting.reduce((t, b) => t + n(b.spent), 0), 2)
    expect(n(s.left)).toBeCloseTo(counting.reduce((t, b) => t + Math.max(0, b.limit_pounds - n(b.spent)), 0), 2)
    expect(s.paused_count).toBe(data.budgets.length - counting.length)
    expect(n(data.other_spending) + n(s.spent)).toBeCloseTo(n(data.total_spent), 2)
    expect(data.summary!.budget_count).toBe(counting.length)
  })

  it('lists the budgetable categories only when asked', () => {
    expect(list().budgetable_categories ?? null).toBeNull()
    const withCats = sampleResponse('/api/v1/budgets', { include: 'categories' }) as BudgetsResponse
    // Purchase categories and, since T-24-3, commitment categories too.
    expect(withCats.budgetable_categories).toEqual(
      ['Bills', 'Eating out', 'Groceries', 'Health', 'Housing', 'Shopping', 'Subscriptions', 'Transport'])
  })

  it('the projection\'s "My budgets" choice uses the sample budgets', () => {
    const p = sampleResponse('/api/v1/analytics/net-worth-projection', { spending_source: 'budgets' }) as {
      contribution_basis: Record<string, unknown>
    }
    const total = n(list().summary_this_cycle!.total_limit)
    expect(p.contribution_basis.spending_used).toBe('budgets')
    expect(n(p.contribution_basis.budgets_monthly)).toBe(total)
    expect(n(p.contribution_basis.spending_applied)).toBe(total)
    expect(p.contribution_basis.budgets_fallback).toBe(false)
  })
})

describe('sample budgets with commitments (T-24-5b)', () => {
  it('coming up is exactly what the demo forecast schedules in the category before payday', () => {
    const data = list()
    const subs = data.budgets.find((b) => b.category === 'Subscriptions')!
    const f = sampleResponse('/api/v1/analytics/forecast', { horizon: 'payday' }) as {
      timeline: { date: string; events: { label: string; amount: number }[] }[]
    }
    const labels = new Set(['Netflix', 'Spotify']) // the sample's subscriptions
    const scheduled = f.timeline.filter((t) => t.date > isoToday() && t.date <= data.cycle.end)
      .flatMap((t) => t.events.filter((e) => labels.has(e.label)).map((e) => [e.label, t.date, -e.amount]))
    expect(scheduled.length).toBeGreaterThan(0)
    expect(subs.coming_up!.items.map((i) => [i.label, i.due_date, n(i.amount)])).toEqual(scheduled)
    expect(n(subs.coming_up!.amount)).toBeCloseTo(scheduled.reduce((t, s) => t + (s[2] as number), 0), 2)
    expect(n(subs.over_by_payday)).toBeCloseTo(Math.max(0, n(subs.spent) + n(subs.coming_up!.amount) - subs.limit_pounds), 2)
    expect(n(subs.over_by_payday)).toBeGreaterThan(0) // the demo shows the "will go over" bar
  })

  it('counts, places and reports commitments by the API rule (synthetic ledger)', () => {
    const tx = (category: string, amount: number, daysAgo: number, kind: 'purchase' | 'commitment', label = 'Club') =>
      ({ category, amount, daysAgo, kind, label })
    const ledger = [
      tx('Subscriptions', 10, 3, 'commitment'), tx('Subscriptions', 300, 2, 'commitment'), // instalment + one-off
      tx('Bills', 40, 2, 'commitment', 'Power'), tx('', 7, 2, 'commitment', 'Mystery'),
      tx('Groceries', 20, 1, 'purchase'),
    ]
    const club = { id: 'sc-Club', label: 'Club', category: 'Subscriptions', amount: 10, nextIn: 27 } // due 3 days ago
    const out = sampleBudgetList(ledger, 6, false, [], [club])
    const subs = out.budgets.find((b) => b.category === 'Subscriptions')!
    expect(n(subs.spent)).toBe(310)
    expect(n(out.not_counted.commitments)).toBe(40)
    expect(n(out.not_counted.commitments_no_category)).toBe(7)
    const share = 7 / 30
    expect(n(subs.pace_spent)).toBeCloseTo(10 + (subs.limit_pounds - 10) * share, 2) // only the £10 instalment is placed
  })
})

describe('sample budget history', () => {
  it('renders Past cycles without crashing', () => {
    const data = list()
    const html = renderToStaticMarkup(
      <HistoryView status="ready" data={history()} now={{ start: data.cycle.start, end: data.cycle.end, spent: 0 }}
        more="idle" retrying={false} onRetry={noop} onShowMore={noop} />,
    )
    expect(html).toContain('Groceries')
  })

  it('completed cycles, oldest first, each 30 days and ending before this cycle', () => {
    const h = history()
    expect(h.cycles.length).toBeGreaterThan(2)
    for (let i = 0; i < h.cycles.length; i++) {
      expect(daysBetween(h.cycles[i].start, h.cycles[i].end)).toBe(29)
      if (i > 0) expect(daysBetween(h.cycles[i - 1].end, h.cycles[i].start)).toBe(1)
    }
    expect(daysBetween(h.cycles[h.cycles.length - 1].end, list().cycle.start)).toBe(1)
  })

  it('every slot is the ledger spend for that cycle, and the totals and counts add up', () => {
    const h = history()
    for (const row of h.budgets) {
      row.cycles.forEach((slot, i) => {
        expect(n(slot.spent)).toBeCloseTo(purchases(slot.start, slot.end, row.category), 2)
        expect(slot.start).toBe(h.cycles[i].start)
        if (!slot.paused) expect(slot.kept).toBe(n(slot.spent) <= slot.limit_pounds!)
      })
      expect(row.kept).toBe(row.cycles.filter((s) => s.kept).length)
    }
    h.cycles.forEach((c, i) => {
      const counted = h.budgets.map((b) => b.cycles[i]).filter((s) => !s.paused)
      expect(n(c.total_spent)).toBeCloseTo(counted.reduce((t, s) => t + n(s.spent), 0), 2)
      expect(n(c.total_limit)).toBe(counted.reduce((t, s) => t + s.limit_pounds!, 0))
      expect(c.on_target).toBe(n(c.total_spent) <= n(c.total_limit))
    })
    expect(h.on_target).toBe(h.cycles.filter((c) => c.on_target).length)
    expect(h.counted).toBe(h.cycles.length)
  })
})

function isoToday() {
  const d = new Date()
  d.setHours(9, 0, 0, 0)
  return d.toISOString().slice(0, 10)
}
function daysBetween(a: string, b: string) {
  return Math.round((Date.parse(b) - Date.parse(a)) / 864e5)
}
function expectedStatus(spent: number, pace: number, limit: number) {
  if (spent > limit) return 'over'
  if (spent > pace * 1.1) return 'ahead_of_pace'
  if (spent < pace * 0.9) return 'under_pace'
  return 'on_pace'
}
