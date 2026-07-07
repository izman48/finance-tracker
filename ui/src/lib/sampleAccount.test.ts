import { describe, it, expect } from 'vitest'
import { sampleResponse } from './sampleAccount'

// The sample account's whole value is that it looks like a REAL working app:
// every headline reconciles to the transactions behind it. These guard that.
const near = (a: number, b: number) => Math.abs(a - b) < 0.02

describe('sample account — internal reconciliation', () => {
  // Default lens is money_out; also test purchases.
  const moneyOut: any = sampleResponse('/api/v1/analytics/spending', { period: 'since_payday' })
  const purchases: any = sampleResponse('/api/v1/analytics/spending', { period: 'since_payday', lens: 'purchases' })

  it('money-out is the default lens', () => {
    expect(moneyOut.lens).toBe('money_out')
    expect(moneyOut.composition).not.toBeNull()
  })

  it('money-out composition sums to the headline', () => {
    const c = moneyOut.composition
    const sum = Number(c.card_repayments) + Number(c.transfers) + Number(c.commitments) + Number(c.other)
    expect(near(sum, Number(moneyOut.total_spent))).toBe(true)
  })

  it('money-out category and merchant totals sum to the headline', () => {
    const cats = moneyOut.by_category.reduce((s: number, c: any) => s + Number(c.total), 0)
    const merch = moneyOut.top_merchants.reduce((s: number, m: any) => s + Number(m.total), 0)
    expect(near(cats, Number(moneyOut.total_spent))).toBe(true)
    expect(near(merch, Number(moneyOut.total_spent))).toBe(true)
  })

  it('money-out drill reconciles: kind=money_out transactions sum to total_spent', () => {
    const list: any = sampleResponse('/api/v1/banking/transactions', {
      kind: 'money_out', page: '1', page_size: '200',
      date_from: moneyOut.period_start, date_to: moneyOut.period_end,
    })
    const sum = list.items.reduce((s: number, t: any) => s + Math.abs(t.amount), 0)
    expect(near(sum, Number(moneyOut.total_spent))).toBe(true)
  })

  it('money-out includes the card repayment (the Amex payoff analogue)', () => {
    expect(Number(moneyOut.composition.card_repayments)).toBeGreaterThan(0)
  })

  it('purchases lens: total = paid from bank + charged to credit, and reconciles to kind=spend', () => {
    expect(near(Number(purchases.total_spent), Number(purchases.paid_from_cash) + Number(purchases.charged_to_credit))).toBe(true)
    const cats = purchases.by_category.reduce((s: number, c: any) => s + Number(c.total), 0)
    expect(near(cats, Number(purchases.total_spent))).toBe(true)
    const list: any = sampleResponse('/api/v1/banking/transactions', {
      kind: 'spend', page: '1', page_size: '200',
      date_from: purchases.period_start, date_to: purchases.period_end,
    })
    const sum = list.items.reduce((s: number, t: any) => s + Math.abs(t.amount), 0)
    expect(near(sum, Number(purchases.total_spent))).toBe(true)
  })

  it('net worth = cash + savings + assets − credit owed (balance sheet reconciles)', () => {
    const s: any = sampleResponse('/api/v1/analytics/summary', {})
    const expected = Number(s.available_cash) + Number(s.savings_total) + Number(s.assets_total) - Number(s.credit_owed)
    expect(near(Number(s.net_worth), expected)).toBe(true)
    const history: any = sampleResponse('/api/v1/analytics/net-worth-history', { months: '12' })
    expect(near(Number(history[history.length - 1].net_worth), Number(s.net_worth))).toBe(true)
  })
})

describe('sample account — unrelated + interactive', () => {
  it('contains no relation to real data (fixed fake merchants/banks)', () => {
    const accts: any = sampleResponse('/api/v1/banking/accounts', {})
    expect(accts.map((a: any) => a.provider_name)).toContain('Everly Bank')
    const me: any = sampleResponse('/api/v1/auth/me', {})
    expect(me.email).toBe('you@sample.example')
  })

  it('filters the fixed ledger (search, category, pagination all work)', () => {
    const all: any = sampleResponse('/api/v1/banking/transactions', { include_excluded: 'true', page: '1', page_size: '200' })
    expect(all.total).toBeGreaterThan(10)

    const groceries: any = sampleResponse('/api/v1/banking/transactions', { category: ['Groceries'], include_excluded: 'true', page_size: '200' })
    expect(groceries.items.every((t: any) => t.category === 'Groceries')).toBe(true)

    const search: any = sampleResponse('/api/v1/banking/transactions', { search: 'fernwood', include_excluded: 'true', page_size: '200' })
    expect(search.items.length).toBeGreaterThan(0)
    expect(search.items.every((t: any) => /fernwood/i.test(t.merchant_name))).toBe(true)

    const page1: any = sampleResponse('/api/v1/banking/transactions', { include_excluded: 'true', page: '1', page_size: '5' })
    expect(page1.items.length).toBe(5)
    expect(page1.total).toBe(all.total)
  })

  it('nothing hidden by default label is available: excluded rows carry a reason', () => {
    const all: any = sampleResponse('/api/v1/banking/transactions', { include_excluded: 'true', page_size: '200' })
    const excluded = all.items.filter((t: any) => t.excluded_reason)
    expect(excluded.some((t: any) => t.excluded_reason === 'card_payment')).toBe(true)
    expect(excluded.some((t: any) => t.excluded_reason === 'internal_transfer')).toBe(true)
  })
})
