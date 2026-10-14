import { describe, expect, it } from 'vitest'
import { aprLabel, bothCounted, liabilityDetail, LOANS_GROUP_LABEL } from './liabilities'
import type { Asset, Liability } from '../services/api'

// ux T-10-0 B.1 (Wealth: loans and finance). Synthetic fixture: A "Lender A"
// loan £9,000 at 11% APR, £200 a month, final payment 1 Jan 2031.
const loan = (over: Partial<Liability> = {}): Liability => ({
  id: 'l-a', kind: 'loan', lender: 'Lender A', balance: '9000.00', balance_as_of: '2026-10-01',
  apr: '11.00', payment: '200.00', cadence: 'monthly', start_date: '2026-11-01', end_date: '2031-01-01',
  opted_out: false, current_balance: '9000.00', next_payment_date: '2026-11-01', payments_remaining: 58,
  payoff_date: '2031-08-01', interest_remaining: '2483.22', total_cost: '11483.22', paid_off: false,
  balance_stale: false, linked_commitment: { id: 'c-1', label: 'Lender A' }, link_result: null, ...over,
})
const asset = (asset_type: string): Asset =>
  ({ id: `a-${asset_type}`, name: 'Car loan', asset_type, valuations: [{ id: 'v', value: '-9000', valued_at: '2026-09-01' }] }) as Asset

describe('liability rows', () => {
  it('L-2: kind, APR, payment, final payment and interest left, as the API gives them', () => {
    expect(liabilityDetail(loan())).toBe('Loan · 11% APR · £200 a month · final payment 1 Jan 2031 · interest left £2,483')
  })

  it('no end date entered: final payment is the computed payoff date', () => {
    expect(liabilityDetail(loan({ end_date: null }))).toContain('final payment 1 Aug 2031')
  })

  it('L-3: repaid irregularly shows no payment, final payment or interest left', () => {
    const c = loan({ kind: 'loan', apr: '5.00', opted_out: true, payment: null, payoff_date: null,
      interest_remaining: null, balance_as_of: '2026-09-03', end_date: null })
    expect(liabilityDetail(c)).toBe('Loan · 5% APR · repaid irregularly · balance as of 3 Sept 2026'.replace('Sept', new Date('2026-09-03').toLocaleDateString('en-GB', { month: 'short' })))
  })

  it('L-18: a paid-off loan says so', () => {
    expect(liabilityDetail(loan({ paid_off: true, current_balance: '0', payoff_date: '2031-01-01' })))
      .toBe('Loan · 11% APR · Paid off 1 Jan 2031')
  })

  it('kind labels and cadences read as words', () => {
    expect(liabilityDetail(loan({ kind: 'finance', cadence: 'fortnightly' }))).toMatch(/^Retail finance · 11% APR · £200 every 2 weeks/)
    expect(liabilityDetail(loan({ kind: 'bnpl', cadence: 'weekly' }))).toMatch(/^Buy now pay later · 11% APR · £200 a week/)
    expect(liabilityDetail(loan({ cadence: 'four_weekly' }))).toContain('£200 every 4 weeks')
  })

  it('APR shows as entered, up to 2 decimals, trailing zeros trimmed', () => {
    expect(aprLabel('10.90')).toBe('10.9%')
    expect(aprLabel('11.00')).toBe('11%')
    expect(aprLabel('0')).toBe('0%')
    expect(aprLabel('19.95')).toBe('19.95%')
  })

  it('the group is renamed', () => {
    expect(LOANS_GROUP_LABEL).toBe('Loans and finance')
  })
})

describe('both-counted notice (A8, sec)', () => {
  it('L-8: a loan or other-debt asset plus a liability', () => {
    expect(bothCounted([asset('loan')], [loan()])).toBe(true)
    expect(bothCounted([asset('other_liability')], [loan()])).toBe(true)
  })

  it('not for a mortgage, nor without a liability', () => {
    expect(bothCounted([asset('mortgage')], [loan()])).toBe(false)
    expect(bothCounted([asset('loan')], [])).toBe(false)
  })
})

describe('a linked bill edited elsewhere (ux B.5)', () => {
  it('the 409 linked_to_liability gives the API message, pointing at Wealth', async () => {
    const { linkedEditMessage } = await import('./liabilities')
    const err = { response: { status: 409, data: { detail: { code: 'linked_to_liability', message: 'This payment follows your loan. Change it on Wealth, under Loans and finance.' } } } }
    expect(linkedEditMessage(err)).toBe('This payment follows your loan. Change it on Wealth, under Loans and finance.')
  })

  it('any other failure is not a linked-bill message', async () => {
    const { linkedEditMessage } = await import('./liabilities')
    expect(linkedEditMessage({ response: { status: 409, data: { detail: 'Conflict' } } })).toBeNull()
    expect(linkedEditMessage(new Error('offline'))).toBeNull()
  })
})
