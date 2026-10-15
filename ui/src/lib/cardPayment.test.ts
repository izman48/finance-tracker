import { describe, expect, it } from 'vitest'
import { canBeCardPayment, isCardOverlapNudge, plannedBody } from './cardPayment'

describe('Card payment flag (T-12-7a, ux O-1)', () => {
  it('only an expense that is not a payment plan can be a card payment', () => {
    expect(canBeCardPayment('expense', 'one_off')).toBe(true)
    expect(canBeCardPayment('expense', 'recurring')).toBe(true)
    expect(canBeCardPayment('expense', 'installment_plan')).toBe(false)
    expect(canBeCardPayment('income', 'one_off')).toBe(false)
  })

  it('the add request carries the tick as a boolean, and false where it cannot apply', () => {
    const one = plannedBody({ name: 'Card bill', direction: 'expense', kind: 'one_off', startDate: '2026-10-31', amount: '400', cardPayment: true })
    expect(one).toEqual({ name: 'Card bill', direction: 'expense', kind: 'one_off', start_date: '2026-10-31', amount: 400, is_card_payment: true })
    const income = plannedBody({ name: 'Refund', direction: 'income', kind: 'one_off', startDate: '2026-10-31', amount: '40', cardPayment: true })
    expect(income.is_card_payment).toBe(false)
    const rec = plannedBody({ name: 'Card bill', direction: 'expense', kind: 'recurring', startDate: '2026-10-31', amount: '400', cadence: 'monthly', cardPayment: false })
    expect(rec).toEqual({ name: 'Card bill', direction: 'expense', kind: 'recurring', start_date: '2026-10-31', amount: 400, cadence: 'monthly', is_card_payment: false })
  })

  it("the overlap nudge is recognised by the API's id prefix", () => {
    expect(isCardOverlapNudge('card_payment_overlap_2026-10-26')).toBe(true)
    expect(isCardOverlapNudge('cash_drag')).toBe(false)
  })
})

describe('Review focuses the first overlapping planned item', () => {
  it('picks the first item the API marks as overlapping, or none', async () => {
    const { firstOverlapId } = await import('./cardPayment')
    expect(firstOverlapId([{ id: 'a' }, { id: 'b', card_payment_overlap: true }, { id: 'c', card_payment_overlap: true }])).toBe('b')
    expect(firstOverlapId([{ id: 'a', card_payment_overlap: false }])).toBeNull()
  })
})
