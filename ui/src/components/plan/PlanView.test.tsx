import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import PlanView, { type PlanViewProps } from './PlanView'
import { planBudget, planResponse } from '../../lib/plan.fixtures'

// Cashflow > Plan (T-24-6, spec "Plan section on Cashflow"). Node suite: static markup.
const html = (props: Partial<PlanViewProps>) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <PlanView status="ready" data={planResponse()} onRetry={() => {}} {...props} />
    </MemoryRouter>,
  )
const text = (h: string) =>
  h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('PlanView', () => {
  it('loading: skeleton and "Loading your plan" as a status', () => {
    const h = html({ status: 'loading', data: null })
    expect(h).toContain('role="status"')
    expect(text(h)).toContain('Loading your plan')
  })

  it('error: the spec sentence and Try again, no server text', () => {
    const h = html({ status: 'error', data: null })
    expect(h).toContain('role="alert"')
    expect(text(h)).toContain("Couldn't load your plan. Your balances and safe to spend are unaffected.")
    expect(h).toMatch(/<button[^>]*>Try again<\/button>/)
  })

  it('a focusable Plan heading, the cycle and the intro', () => {
    const h = html({})
    expect(h).toMatch(/<h2[^>]*id="plan-heading"[^>]*tabindex="-1"[^>]*>Plan<\/h2>/)
    expect(text(h)).toContain('30 Oct – 29 Nov · 16 days left')
    expect(text(h)).toContain('Where this pay cycle goes. Every line opens to the transactions behind it.')
  })

  it('collapsed: the four lines with the API figures, and the sum that reconciles them', () => {
    const t = text(html({}))
    expect(t).toContain('Income 1 of 2 received £3,100.00')
    expect(t).toContain('Fixed 2 of 4 paid · £29.50 still to pay £989.49')
    expect(t).toContain('Budgets 2 limits · £450.50 spent · £40.00 coming up £550.00')
    expect(t).toContain('Not planned What is left after Fixed and Budgets £1,560.51')
    expect(t).toContain('£3,100.00 − £989.49 − £550.00 = £1,560.51')
    expect(t).toContain('Income − Fixed − Budget limits = Not planned')
  })

  it('spending outside budgets shows without opening anything, neutral', () => {
    const h = html({})
    expect(text(h)).toContain('Spent so far in categories with no budget £1,700.00')
    expect(text(h)).toContain('That is £139.49 more than the £1,560.51 left.')
    expect(h).not.toMatch(/text-neg|chip-neg/)
  })

  it('rows are buttons that start collapsed and control their hidden panel', () => {
    const h = html({})
    const rows = [...h.matchAll(/<button[^>]*aria-expanded="(true|false)"[^>]*aria-controls="([^"]+)"/g)]
    expect(rows.length).toBeGreaterThanOrEqual(3 + 3 + 2) // Income, Fixed, Budgets, 3 groups, 2 budgets
    for (const [, expanded, id] of rows) {
      expect(expanded).toBe('false')
      expect(h).toMatch(new RegExp(`id="${id}"[^>]*hidden`))
    }
  })

  it('Fixed groups list each item with paid or due status; no category is its own group', () => {
    const t = text(html({}))
    expect(t).toContain('Housing 1 of 1 paid £950.00')
    expect(t).toContain('Rent Paid 1 Nov £950.00')
    expect(t).toContain('Cloudbox Due 21 Nov £4.50')
    expect(t).toContain('No category 0 of 1 paid £25.00')
  })

  it('a commitment not due this cycle shows £0.00 and says so', () => {
    expect(text(html({}))).toContain('Annual pass Next due outside this cycle £0.00')
  })

  it('income items say received or expected', () => {
    const t = text(html({}))
    expect(t).toContain('Salary Received £2,800.00')
    expect(t).toContain('Side job Expected 28 Nov £300.00')
  })

  it('a budget row: spent of limit, status in words, coming up; opens to its commitments and other purchases', () => {
    const t = text(html({}))
    expect(t).toContain('Eating out £330.50 spent of £300.00 · Over by £30.50 · £40.00 coming up £300.00')
    expect(t).toContain('Groceries £120.00 spent of £250.00 · Under pace £250.00')
    expect(t).toContain('Pizza club Paid 6 Nov £20.00')
    expect(t).toContain('Pizza club Due 20 Nov £20.00')
    expect(t).toContain('Other purchases Paid £310.50')
  })

  it('a used budget says "Budget used", not a pace', () => {
    const data = planResponse()
    data.budgets.items = [planBudget({ spent: '250.00', status: 'budget_used' })]
    expect(text(html({ data }))).toContain('£250.00 spent of £250.00 · Budget used')
  })

  it('no budgets: "No budgets set" with Suggest budgets', () => {
    const data = planResponse({ budgets: { limits_total: '0.00', spent: '0.00', coming_up: '0.00', count: 0, items: [] } })
    const h = html({ data })
    expect(text(h)).toContain('No budgets set')
    expect(h).toMatch(/<a[^>]*href="\/insights\?section=budgets"[^>]*>Suggest budgets<\/a>/)
  })

  it('no commitments: "Nothing scheduled" with Add a commitment', () => {
    const data = planResponse({ fixed: { total: '0.00', paid: '0.00', to_pay: '0.00', paid_count: 0, count: 0, groups: [] } })
    const h = html({ data })
    expect(text(h)).toContain('Nothing scheduled')
    expect(h).toMatch(/<a[^>]*href="\/commitments"[^>]*>Add a commitment<\/a>/)
  })

  it('no income: says so, hides Not planned and the reconciliation', () => {
    const data = planResponse({ income: { total: '0.00', received_count: 0, expected_count: 0, items: [] } })
    const h = html({ data })
    const t = text(h)
    expect(t).toContain('No income found this cycle')
    expect(h).toMatch(/<a[^>]*href="\/commitments"[^>]*>Check your income<\/a>/)
    expect(t).not.toContain('Not planned')
    expect(t).not.toContain('Income − Fixed − Budget limits')
  })

  it('labels and categories render as text, never markup (sec T-24-6)', () => {
    const data = planResponse()
    data.fixed.groups[0].category = '<b>Housing</b>'
    data.fixed.groups[0].items[0].label = '<img src=x onerror=alert(1)>'
    const h = html({ data })
    expect(h).not.toContain('<img src=x')
    expect(h).not.toContain('<b>Housing')
    expect(h).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })
})
