import { describe, expect, it } from 'vitest'
import { cardSettingsPath, cardsWithoutRepayment, repaymentNotSetUp, settingsAccountFor } from './credit'
import type { SummaryAccount } from '../types'

// T-10-12 (owner D8): a card that owes money but has no repayment set up is
// left out of the forecast (repayments.repayment_events), so the UI says so.
describe('repaymentNotSetUp', () => {
  const owing = (over: Partial<SummaryAccount>) =>
    ({
      id: 'c1', role: 'credit', credit_owed: '250.00',
      repayment_cadence: null, repayment_strategy: null, ...over,
    }) as SummaryAccount

  it('is true for a card that owes money with nothing stored', () => {
    expect(repaymentNotSetUp(owing({}))).toBe(true)
  })

  it('is true with a strategy that needs a pay day but no pay day stored', () => {
    for (const strategy of ['full_balance', 'fixed', 'installments', 'minimum_percent']) {
      expect(repaymentNotSetUp(owing({ repayment_strategy: strategy }))).toBe(true)
    }
  })

  it('is false once a pay day is stored, whatever the strategy', () => {
    expect(repaymentNotSetUp(owing({ repayment_cadence: 'monthly' }))).toBe(false)
    expect(repaymentNotSetUp(owing({ repayment_cadence: 'end_of_month', repayment_strategy: 'full_balance' }))).toBe(false)
  })

  it('is false for statement balance and scheduled, which need no pay day', () => {
    expect(repaymentNotSetUp(owing({ repayment_strategy: 'statement_balance' }))).toBe(false)
    expect(repaymentNotSetUp(owing({ repayment_strategy: 'scheduled' }))).toBe(false)
  })

  it('is false for a card that owes nothing or is in credit, and for non-cards', () => {
    expect(repaymentNotSetUp(owing({ credit_owed: '0' }))).toBe(false)
    expect(repaymentNotSetUp(owing({ credit_owed: '-20.00' }))).toBe(false)
    expect(repaymentNotSetUp(owing({ credit_owed: null }))).toBe(false)
    expect(repaymentNotSetUp(owing({ role: 'spending' }))).toBe(false)
  })

  it('cardsWithoutRepayment keeps only those cards, and skips excluded accounts', () => {
    const accounts = [
      owing({ id: 'a' }),
      owing({ id: 'b', repayment_strategy: 'statement_balance' }),
      owing({ id: 'c', role: 'excluded' }),
    ]
    expect(cardsWithoutRepayment(accounts).map((a) => a.id)).toEqual(['a'])
  })
})

describe('card settings link', () => {
  const accounts = [
    { id: '11111111-1111-4111-8111-111111111111', role: 'credit' },
    { id: 'sa1', role: 'spending' },
  ] as SummaryAccount[]

  it('points at Wealth with the card id, encoded', () => {
    expect(cardSettingsPath('11111111-1111-4111-8111-111111111111')).toBe(
      '/networth?settings=11111111-1111-4111-8111-111111111111',
    )
    expect(cardSettingsPath('a b&c')).toBe('/networth?settings=a%20b%26c')
  })

  it('opens only an account the summary already holds', () => {
    expect(settingsAccountFor('?settings=11111111-1111-4111-8111-111111111111', accounts)?.id).toBe(
      '11111111-1111-4111-8111-111111111111',
    )
    expect(settingsAccountFor('?settings=unknown', accounts)).toBeNull()
    expect(settingsAccountFor('', accounts)).toBeNull()
    expect(settingsAccountFor('?other=1', accounts)).toBeNull()
  })
})
