import { describe, it, expect } from 'vitest'
import { sampleResponse } from './sampleAccount'
import { cardsWithoutRepayment } from './credit'

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

  it('T-10-12: the sample card owes money and has a repayment set up, so no D8 notice shows', () => {
    const s: any = sampleResponse('/api/v1/analytics/summary', {})
    expect(s.accounts.some((a: any) => a.role === 'credit' && Number(a.credit_owed) > 0)).toBe(true)
    expect(cardsWithoutRepayment(s.accounts)).toEqual([])
  })

  it('T-10-14a: total_owed is cards + liabilities, and the card statement matches the statements response', () => {
    const s: any = sampleResponse('/api/v1/analytics/summary', {})
    expect(near(Number(s.total_owed), Number(s.credit_owed) + Number(s.liabilities_total))).toBe(true)
    const card = s.accounts.find((a: any) => a.role === 'credit')
    const st: any = sampleResponse('/api/v1/analytics/accounts/sa4/statements', {})
    expect(card.statement).toEqual({
      statement_balance: st.current.statement_balance, due_date: st.current.due_date, paid: false, missing: false,
    })
    for (const a of s.accounts.filter((x: any) => x.role !== 'credit')) expect('statement' in a).toBe(false)
  })

  it('net worth = cash + savings + assets − credit owed − liabilities (balance sheet reconciles)', () => {
    const s: any = sampleResponse('/api/v1/analytics/summary', {})
    const expected = Number(s.available_cash) + Number(s.savings_total) + Number(s.assets_total)
      - Number(s.credit_owed) - Number(s.liabilities_total)
    expect(near(Number(s.net_worth), expected)).toBe(true)
    const history: any = sampleResponse('/api/v1/analytics/net-worth-history', { months: '12' })
    expect(near(Number(history[history.length - 1].net_worth), Number(s.net_worth))).toBe(true)
  })

  it('the sample liabilities reconcile with the summary, position and history (T-10-10)', () => {
    const loans: any[] = sampleResponse('/api/v1/liabilities', {}) as any[]
    const total = loans.reduce((t, l) => t + Number(l.current_balance), 0)
    const s: any = sampleResponse('/api/v1/analytics/summary', {})
    const pos: any = sampleResponse('/api/v1/analytics/net-worth-position', {})
    const history: any = sampleResponse('/api/v1/analytics/net-worth-history', { months: '12' })
    expect(loans.length).toBeGreaterThan(0)
    expect(near(Number(s.liabilities_total), total)).toBe(true)
    expect(near(Number(pos.liabilities), total)).toBe(true)
    expect(near(Number(pos.net_worth), Number(pos.bank) + Number(pos.assets) - Number(pos.liabilities))).toBe(true)
    const today = history[history.length - 1]
    expect(near(Number(today.net_worth), Number(today.bank) + Number(today.assets) - Number(today.liabilities))).toBe(true)
    // Highest APR first, as the API sorts them (ux L-1).
    const aprs = loans.map((l) => Number(l.apr))
    expect(aprs).toEqual([...aprs].sort((a, b) => b - a))
  })

  it('the sample total owed is the card owed plus the liabilities (T-10-14d)', () => {
    const s: any = sampleResponse('/api/v1/analytics/summary', {})
    expect(near(Number(s.total_owed), Number(s.credit_owed) + Number(s.liabilities_total))).toBe(true)
  })

  it("the sample card's statement is the same bill as its next repayment (T-10-14)", () => {
    const s: any = sampleResponse('/api/v1/analytics/summary', {})
    const card = s.accounts.find((a: any) => a.role === 'credit')
    const bill = s.next_repayments.find((r: any) => r.account_id === card.id)
    expect(Number(card.statement.statement_balance)).toBe(Number(bill.amount))
    expect(card.statement.due_date).toBe(bill.due_date)
    expect(s.accounts.filter((a: any) => a.role !== 'credit').every((a: any) => !('statement' in a))).toBe(true)
  })

  it('per-account credit_owed is positive and sums to the headline credit owed', () => {
    const s: any = sampleResponse('/api/v1/analytics/summary', {})
    const cards = s.accounts.filter((a: any) => a.role === 'credit')
    expect(cards.every((a: any) => Number(a.credit_owed) > 0)).toBe(true)
    const sum = cards.reduce((t: number, a: any) => t + Number(a.credit_owed), 0)
    expect(near(sum, Number(s.credit_owed))).toBe(true)
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

describe('sample card statement (T-10-6)', () => {
  it('reconciles with the sample summary: same amount and day as the next repayment', () => {
    const summary = sampleResponse('/api/v1/analytics/summary', {}) as { next_repayments: { amount: number; due_date: string }[] }
    const s = sampleResponse('/api/v1/analytics/accounts/sa4/statements', {}) as CardStatementsShape
    expect(Number(s.next_payment.amount)).toBe(summary.next_repayments[0].amount)
    expect(s.next_payment.date).toBe(summary.next_repayments[0].due_date)
    // statement_balance (T-12-7a): the still-due amount on the due date, the
    // spend since the statement on the next pay day.
    expect(Number(s.current.amount_still_due)).toBe(summary.next_repayments[0].amount)
    expect(Number(s.current.unbilled)).toBe(summary.next_repayments[1].amount)
  })

  it('a non-card account has no statement', () => {
    expect(sampleResponse('/api/v1/analytics/accounts/sa1/statements', {})).toMatchObject({ statements: [], current: null })
  })
})

type CardStatementsShape = {
  current: { amount_still_due: string; unbilled: string }
  next_payment: { amount: string; date: string }
}

// T-10-15b: demo mode answers spending_source as the API does. The sample has
// no budgets, so "budgets" (and no choice) falls back to the average.
describe('sample projection spending', () => {
  const basis = (q: Record<string, unknown>) =>
    (sampleResponse('/api/v1/analytics/net-worth-projection', q) as any).contribution_basis
  // No spending_source keeps the legacy answer, as the API does (tested by the API).
  // The sample has budgets since T-11-8, so "budgets" uses their total
  // (sampleBudgets.test.tsx ties it to the served budgets), not the average.
  it('budgets use the sample budgets total, not the average', () => {
    const b = basis({ spending_source: 'budgets' })
    expect(b.budgets_fallback).toBe(false)
    expect(b.spending_choice).toBe('budgets')
    expect(b.spending_used).toBe('budgets')
    expect(Number(b.spending_applied)).toBe(Number(b.budgets_monthly))
    expect(Number(b.spending_applied)).not.toBe(Number(b.avg_spending_monthly))
  })
  it('average with an estimate uses the estimate', () => {
    const b = basis({ spending_source: 'average', monthly_spending: '900' })
    expect(b.spending_used).toBe('estimate')
    expect(Number(b.spending_applied)).toBe(900)
  })
  it('"none" and the old no-spending flag still subtract spending, as the API (T-12-0)', () => {
    for (const q of [{ spending_source: 'none' }, { subtract_spending: 'false' }]) {
      const b = basis(q)
      expect(b.spending_subtracted).toBe(true)
      expect(Number(b.spending_applied)).toBeGreaterThan(0)
    }
  })
})
