import { describe, expect, it } from 'vitest'
import { billPartsLine, cardBillLabel } from './cardBill'

// T-12-7a part 2 (lead decision 2026-10-15; ux C-1..C-4): the API says what
// a card bill is made of; the browser only words it.
describe('card bill label and line 2', () => {
  it('a statement is "{card} bill"; a projection says so', () => {
    expect(cardBillLabel('Amex Gold', false)).toBe('Amex Gold bill')
    expect(cardBillLabel('Amex Gold', true)).toBe('Amex Gold bill (projected)')
  })

  it('line 2 spells the parts: spent since, or the balance with no statement', () => {
    expect(billPartsLine([{ kind: 'spent_since', amount: '140.00' }])).toBe('Spent since £140.00')
    expect(billPartsLine([{ kind: 'balance', amount: 640.3 }])).toBe('Balance £640.30')
  })

  it('a statement alone needs no line 2; parts at 0 are left out; none, none', () => {
    expect(billPartsLine([{ kind: 'statement', amount: '500.00' }])).toBeNull()
    expect(billPartsLine([{ kind: 'spent_since', amount: '0.00' }])).toBeNull()
    expect(billPartsLine([])).toBeNull()
    expect(billPartsLine(undefined)).toBeNull()
  })

  it('several parts join with " + " in the fixed order, first one capitalised', () => {
    expect(billPartsLine([{ kind: 'spent_since', amount: 140 }, { kind: 'statement', amount: 500 }]))
      .toBe('Still due £500.00 + spent since £140.00')
  })
})
