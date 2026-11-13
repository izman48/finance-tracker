import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import PlanView, { type PlanViewProps } from './PlanView'
import { planBudget, planResponse } from '../../lib/plan.fixtures'

// Cashflow > Plan (T-25-2: Money in, Commitments by group, Budgets, Left over). Node suite: static markup.
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

  it('a focusable Plan heading and the cycle', () => {
    const h = html({})
    expect(h).toMatch(/<h2[^>]*id="plan-heading"[^>]*tabindex="-1"[^>]*>Plan<\/h2>/)
    expect(text(h)).toContain('30 Oct – 29 Nov · 16 days left')
  })

  it('collapsed: the four lines with the API figures, and the sum that reconciles them', () => {
    const t = text(html({}))
    expect(t).toContain('Money in 3 received · 1 expected £3,750.00')
    expect(t).toContain('Commitments 2 of 6 paid £1,419.49')
    expect(t).toContain('Budgets 2 limits, £550.00 in all £620.50')
    expect(t).toContain('Left over £1,710.01')
    expect(t).toContain('£3,750.00 − £1,419.49 − £620.50 = £1,710.01')
    expect(t).toContain('Money in − Commitments − Budgets = Left over')
  })

  it('rows are buttons that start collapsed and control their hidden panel', () => {
    const h = html({})
    const rows = [...h.matchAll(/<button[^>]*aria-expanded="(true|false)"[^>]*aria-controls="([^"]+)"/g)]
    expect(rows.length).toBe(3 + 3 + 2) // Money in, Commitments, Budgets; 3 groups; 2 budgets
    for (const [, expanded, id] of rows) {
      expect(expanded).toBe('false')
      expect(h).toMatch(new RegExp(`id="${id}"[^>]*hidden`))
    }
  })

  it('rows show the 2px accent focus ring', () => {
    const rows = [...html({}).matchAll(/<button[^>]*aria-expanded[^>]*>/g)].map((m) => m[0])
    expect(rows.every((r) => r.includes('focus-visible:outline-2') && r.includes('focus-visible:outline-accent/60'))).toBe(true)
  })

  it('money in lists each income and credit, received or expected', () => {
    const t = text(html({}))
    expect(t).toContain('Salary Received 30 Oct £2,800.00')
    expect(t).toContain('GIFT FROM GRAN Received 8 Nov £50.00')
    expect(t).toContain('Side job Expected 28 Nov £300.00')
  })

  it('each commitment group opens to its items: paid, coming or not seen yet', () => {
    const t = text(html({}))
    expect(t).toContain('Rent & bills (3) 1 of 3 paid £1,305.00')
    expect(t).toContain('Rent Paid 1 Nov £1,200.00')
    expect(t).toContain('Energy co Not seen yet, due 10 Nov £85.00')
    expect(t).toContain('Phone Coming 16 Nov £20.00')
    expect(t).toContain('Subscriptions (2) 1 of 2 paid £14.49')
    expect(t).toContain('Streamly Paid 4 Nov £9.99')
    expect(t).toContain('Savings (1) 0 of 1 paid £100.00')
  })

  it('a budget row: spent of limit, status in words, coming up; opens to its commitments and other purchases', () => {
    const t = text(html({}))
    expect(t).toContain('Eating out £330.50 spent of £300.00 · Over by £30.50 · £40.00 coming up £370.50')
    expect(t).toContain('Groceries £120.00 spent of £250.00 · Under pace £250.00')
    expect(t).toContain('Pizza club Paid 6 Nov £20.00')
    expect(t).toContain('Pizza club Coming 20 Nov £20.00')
    expect(t).toContain('Other purchases Paid £310.50')
  })

  it('other purchases of £0.00 are not listed', () => {
    const data = planResponse()
    data.budgets.items[0].other_purchases = '0.00'
    const t = text(html({ data }))
    expect(t).not.toContain('Other purchases Paid £0.00')
    expect(t).toContain('Other purchases Paid £120.00')
  })

  it('a used budget says "Budget used", not a pace', () => {
    const data = planResponse()
    data.budgets.items = [planBudget({ spent: '250.00', status: 'budget_used' })]
    expect(text(html({ data }))).toContain('£250.00 spent of £250.00 · Budget used')
  })

  it('when commitments and budgets come to more than money in, it says so', () => {
    const t = text(html({ data: planResponse({ left_over: '-122.28' }) }))
    expect(t).toContain('Commitments and Budgets come to £122.28 more than your money in this cycle.')
  })

  it('no budgets: "No budgets set" with Suggest budgets', () => {
    const h = html({ data: planResponse({ budgets: { limits_total: '0.00', planned_total: '0.00', items: [] } }) })
    expect(text(h)).toContain('No budgets set')
    expect(h).toMatch(/<a[^>]*href="\/insights\?section=budgets"[^>]*>Suggest budgets<\/a>/)
  })

  it('no commitments: "Nothing scheduled" with Add a commitment', () => {
    const h = html({ data: planResponse({ commitments: { total: '0.00', groups: [] } }) })
    expect(text(h)).toContain('Nothing scheduled')
    expect(h).toMatch(/<a[^>]*href="\/commitments"[^>]*>Add a commitment<\/a>/)
  })

  it('no money in: says so, hides Left over and the reconciliation', () => {
    const h = html({ data: planResponse({ money_in: { total: '0.00', items: [] } }) })
    const t = text(h)
    expect(t).toContain('No money in found this cycle')
    expect(h).toMatch(/<a[^>]*href="\/commitments"[^>]*>Check your income<\/a>/)
    expect(t).not.toContain('Left over')
  })

  it('labels and group names render as text, never markup (sec T-24-6)', () => {
    const data = planResponse()
    data.commitments.groups[0].name = '<b>Housing</b>'
    data.commitments.groups[0].items[0].label = '<img src=x onerror=alert(1)>'
    const h = html({ data })
    expect(h).not.toContain('<img src=x')
    expect(h).not.toContain('<b>Housing')
    expect(h).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })
})
