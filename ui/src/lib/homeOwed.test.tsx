import { describe, expect, it } from 'vitest'
import { homeUpcomingLabel, investmentsRow, loanPaymentLabel, owedRow } from './homeOwed'
import { renderToStaticMarkup } from 'react-dom/server'
import { buildUpcoming } from './upcoming'
import UpcomingLabel from '../components/UpcomingLabel'

// ux T-10-13 Home (G-10, G-11, G-12). Synthetic fixture: card owed £6,000,
// loan £9,000, so total_owed £15,000.00 from the API.
describe('Home "Total owed" (H2)', () => {
  it("G-10: the API's total_owed, labelled Total owed", () => {
    expect(owedRow({ total_owed: '15000.00', credit_owed: 6000 })).toEqual({ label: 'Total owed', amount: 15000 })
  })

  it('G-10: hidden at £0', () => {
    expect(owedRow({ total_owed: '0.00', credit_owed: 0 })).toBeNull()
    expect(owedRow({ total_owed: 0, credit_owed: -50 })).toBeNull()
  })

  it('before the API sends total_owed, the row stays as it was (no browser sum)', () => {
    expect(owedRow({ credit_owed: 6000 })).toEqual({ label: 'Owed on credit', amount: 6000 })
  })
})

describe('Home coming-up card row (H1)', () => {
  it('G-12: a card repayment reads "{card} bill"; other rows keep their label', () => {
    const rows = buildUpcoming([], [{ account_id: 'card-1', label: 'Test Card', amount: 5000, due_date: '2026-10-31' }], [], '2026-10-15', 3)
    expect(rows.map((u) => homeUpcomingLabel(u))).toEqual(['Test Card bill'])
    expect(homeUpcomingLabel({ key: 'c-1', label: 'Rent', amount: 950, date: '2026-10-20', income: false })).toBe('Rent')
  })
})

describe('Home coming-up loan row (P2, owner 2026-10-15)', () => {
  it('a linked loan payment reads "{lender} loan payment"', () => {
    const row = { key: 'c-9', label: 'LOAN DD', amount: 200, date: '2026-10-20', income: false, commitmentId: 'c-9' }
    expect(homeUpcomingLabel(row, new Map([['c-9', 'Example Bank']]))).toBe('Example Bank loan payment')
    expect(homeUpcomingLabel(row, new Map())).toBe('LOAN DD')
  })

  it('a lender that already says "loan" reads "{lender} payment"', () => {
    const row = { key: 'c-9', label: 'LOAN DD', amount: 200, date: '2026-10-20', income: false, commitmentId: 'c-9' }
    expect(homeUpcomingLabel(row, new Map([['c-9', 'Northgate Motor Loans']]))).toBe('Northgate Motor Loans payment')
  })

  it('loanLenders maps each linked bill to its lender', async () => {
    const { loanLenders } = await import('./homeOwed')
    const map = loanLenders([
      { lender: 'Example Bank', linked_commitment: { id: 'c-9', label: 'LOAN DD' } },
      { lender: 'Irregular Lender', linked_commitment: null },
    ])
    expect([...map.entries()]).toEqual([['c-9', 'Example Bank']])
  })
})

describe('the lender in the loan label is plain text (sec on T-10-14d)', () => {
  const row = { key: 'c-9', label: 'LOAN DD', amount: 200, date: '2026-10-20', income: false, commitmentId: 'c-9' }

  it('a 100-character lender is kept whole', () => {
    const lender = 'L'.repeat(100)
    expect(homeUpcomingLabel(row, new Map([['c-9', lender]]))).toBe(`${lender} loan payment`)
  })

  it('markup in a lender renders as text', () => {
    const label = homeUpcomingLabel(row, new Map([['c-9', '<b>x</b>']]))
    const html = renderToStaticMarkup(<UpcomingLabel item={{ ...row, label }} linkMarker={false} />)
    expect(html).not.toContain('<b>')
    expect(html).toContain('&lt;b&gt;x&lt;/b&gt; loan payment')
  })
})

describe('loanPaymentLabel (owner P2, one rule shared with Cashflow)', () => {
  it('adds "loan payment" to a lender', () => {
    expect(loanPaymentLabel('Lender A')).toBe('Lender A loan payment')
  })
  it('says only "payment" when the lender already contains "loan", in any case', () => {
    expect(loanPaymentLabel('Personal loan')).toBe('Personal loan payment')
    expect(loanPaymentLabel('LOANCO')).toBe('LOANCO payment')
  })
})

describe('Home Investments row (ux T-11-2 L-3, L-4)', () => {
  it("shows the API's investments_total when above 0, and nothing otherwise", () => {
    expect(investmentsRow({ investments_total: '28000.00' })).toEqual({ label: 'Investments', amount: 28000 })
    expect(investmentsRow({ investments_total: '0.00' })).toBeNull()
    expect(investmentsRow({})).toBeNull()
  })
})
