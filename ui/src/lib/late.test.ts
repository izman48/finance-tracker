import { describe, expect, it } from 'vitest'
import { daysLate, lateIncomeNote, lateLine } from './late'

// ux spec section 3 (L1, L2). Late income is shown, never counted.
describe('late income copy', () => {
  it('L1: the sub-line counts whole days, singular for one', () => {
    expect(daysLate('2026-10-05', '2026-10-10')).toBe(5)
    expect(lateLine('2026-10-05', 5)).toBe('Expected 5 Oct · 5 days late · Not counted until it arrives.')
    expect(lateLine('2026-10-09', 1)).toBe('Expected 9 Oct · 1 day late · Not counted until it arrives.')
  })

  it('L2: one late payment, several, or none', () => {
    expect(lateIncomeNote([{ amount: '1203.00' }])).toBe(
      "£1,203.00 of expected income is late and isn't counted in this forecast.",
    )
    expect(lateIncomeNote([{ amount: '1500' }, { amount: 500 }])).toBe(
      "£2,000.00 of expected income is late (2 payments) and isn't counted in this forecast.",
    )
    expect(lateIncomeNote([])).toBeNull()
  })
})
