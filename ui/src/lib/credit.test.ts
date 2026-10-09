import { describe, expect, it } from 'vitest'
import { cardsOwing, creditAmount } from './credit'
import type { SummaryAccount } from '../types'

const card = (credit_owed: number | string | null, role = 'credit') =>
  ({ id: String(Math.random()), role, credit_owed }) as unknown as SummaryAccount

describe('creditAmount', () => {
  it('shows money owed as a plain amount in the warning tone', () => {
    expect(creditAmount(642.31)).toEqual({ text: '£642.31', tone: 'text-warn' })
  })

  it('shows an overpaid card as "in credit" in the positive tone, never a negative owed', () => {
    expect(creditAmount('-50')).toEqual({ text: '£50.00 in credit', tone: 'text-pos' })
  })

  it('treats a settled card as owing nothing', () => {
    expect(creditAmount(0)).toEqual({ text: '£0.00', tone: 'text-warn' })
  })
})

describe('cardsOwing', () => {
  it('counts only credit accounts that owe money', () => {
    const accounts = [card(642.31), card('400.00'), card(-50), card(0), card(null, 'spending')]
    expect(cardsOwing(accounts)).toHaveLength(2)
  })
})
