import { describe, expect, it } from 'vitest'
import { aprLabel, bothCounted, endDateWarning, equityLine, liabilityDetail, liabilityName, linkedChip, LOANS_GROUP_LABEL, mortgageDetail, needsProperty } from './liabilities'
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

  it('not without a liability (a mortgage asset counts too since T-12-6: see below)', () => {
    expect(bothCounted([asset('loan')], [])).toBe(false)
  })
})

describe('a linked bill edited elsewhere (ux B.5)', () => {
  it('the 409 linked_to_liability gives the API message, pointing at Wealth', async () => {
    const { linkedEditMessage } = await import('./liabilities')
    const err = { response: { status: 409, data: { detail: { code: 'linked_to_liability', message: 'This payment follows your loan. Change it on Wealth, under Loans and finance.' } } } }
    expect(linkedEditMessage(err)).toBe('This payment follows your loan. Change it on Wealth, under Loans and finance.')
  })

  it("an investment's bill gives the API's message too (409 linked_to_holding)", async () => {
    const { linkedEditMessage } = await import('./liabilities')
    const message = 'This payment follows your investment. Change it on Wealth, under Investments.'
    const err = { response: { status: 409, data: { detail: { code: 'linked_to_holding', message } } } }
    expect(linkedEditMessage(err)).toBe(message)
  })

  it("only an investment's bill carries the Follows your investment chip", async () => {
    const { linkedChip } = await import('./liabilities')
    expect(linkedChip({ linked_holding: true })).toBe('Follows your investment')
    expect(linkedChip({ linked_holding: false, linked_liability: true })).toBeNull()
    expect(linkedChip({})).toBeNull()
  })

  it('any other failure is not a linked-bill message', async () => {
    const { linkedEditMessage } = await import('./liabilities')
    expect(linkedEditMessage({ response: { status: 409, data: { detail: 'Conflict' } } })).toBeNull()
    expect(linkedEditMessage(new Error('offline'))).toBeNull()
  })
})

// T-12-7b part 2 (ux T-12-1 "Mortgage and equity"). Synthetic: Sample Bank,
// £120,000 at 4.5%, £780 a month; Sample House £250,000.
describe('mortgage rows and equity', () => {
  const mortgage = (over: Partial<Liability> = {}) => loan({
    kind: 'mortgage', lender: 'Sample Bank', balance: '120000.00', current_balance: '120000.00', apr: '4.50',
    payment: '780.00', end_date: null, payoff_date: '2051-11-01', property_asset_id: 'h1', ...over,
  })
  const house = { id: 'h1', name: 'Sample House', asset_type: 'property' } as Asset

  it('the row is named "{lender} mortgage"; a loan keeps its lender', () => {
    expect(liabilityName(mortgage())).toBe('Sample Bank mortgage')
    expect(liabilityName(loan())).toBe('Lender A')
  })
  it('line 2: kind, APR, payment, final payment month, and the property it is for', () => {
    expect(mortgageDetail(mortgage(), [house])).toBe('Mortgage · 4.5% APR · £780 a month · final payment Nov 2051 · for Sample House')
  })
  it('no property chosen: line 2 stops before it, and the row offers Choose a property', () => {
    expect(mortgageDetail(mortgage({ property_asset_id: null }), [house])).toBe('Mortgage · 4.5% APR · £780 a month · final payment Nov 2051')
    expect(needsProperty(mortgage({ property_asset_id: null }))).toBe(true)
    expect(needsProperty(mortgage())).toBe(false)
    expect(needsProperty(loan())).toBe(false)
  })
  it('the equity line and its spoken form, from the API figures; negative keeps its minus', () => {
    expect(equityLine({ ...house, value_today: '250000.00', mortgage_owed: '120000.00', equity: '130000.00' } as Asset)).toEqual({
      text: 'Value £250,000 − mortgage £120,000 = equity £130,000',
      label: 'Value £250,000 minus mortgage £120,000 equals equity £130,000',
      figure: '£130,000',
    })
    expect(equityLine({ ...house, value_today: '250000.00', mortgage_owed: '255000.00', equity: '-5000.00' } as Asset)!.text)
      .toBe('Value £250,000 − mortgage £255,000 = equity −£5,000')
    expect(equityLine({ ...house, value_today: '250000.00', mortgage_owed: null, equity: null } as Asset)).toBeNull()
  })
  it('the Commitments chip for a mortgage payment', () => {
    expect(linkedChip({ linked_liability: true, linked_mortgage: true })).toBe('Follows your mortgage')
    expect(linkedChip({ linked_liability: true, linked_mortgage: false })).toBeNull()
  })
  it('a legacy mortgage asset beside a liability shows the both-counted notice', () => {
    expect(bothCounted([asset('mortgage')], [loan()])).toBe(true)
  })
})


// T-12-12 (T-10-7a review): the schedule nilu works out ends well after the
// final payment the user entered, which usually means a wrong APR or payment.
describe('end date vs computed payoff', () => {
  it('warns when the payoff is more than a month after the final payment entered', () => {
    // The fixture: final payment 1 Jan 2031, nilu's payoff 1 Aug 2031.
    expect(endDateWarning(loan())).toBe(
      'nilu works out the last payment as Aug 2031, after the final payment you entered (Jan 2031). Check the APR and payment.',
    )
  })

  it('stays quiet within a month, with no end date, no payoff, paid off or opted out', () => {
    expect(endDateWarning(loan({ payoff_date: '2031-01-25' }))).toBeNull()
    expect(endDateWarning(loan({ payoff_date: '2030-06-01' }))).toBeNull()
    expect(endDateWarning(loan({ end_date: null }))).toBeNull()
    expect(endDateWarning(loan({ payoff_date: null }))).toBeNull()
    expect(endDateWarning(loan({ paid_off: true }))).toBeNull()
    expect(endDateWarning(loan({ opted_out: true }))).toBeNull()
  })
})
