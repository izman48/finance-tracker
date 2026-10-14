import { describe, expect, it } from 'vitest'
import { cardFigure, cashflowGroups, heroSubline } from './cashflowGroups'
import type { SummaryAccount } from '../types'

// ux T-10-13 (G-1..G-7). Synthetic fixture: Test Current £1,000.00, Test
// Savings £2,000.00, Test Card owed £6,000.00.
const acc = (over: Partial<SummaryAccount>) =>
  ({ id: over.display_name, provider_name: 'Test Bank', current_balance: 0, credit_owed: null, ...over }) as SummaryAccount
const current = acc({ display_name: 'Test Current', role: 'spending', current_balance: 1000 })
const savings = acc({ display_name: 'Test Savings', role: 'savings', current_balance: '2000.00' as unknown as number })
const card = acc({ display_name: 'Test Card', role: 'credit', credit_owed: '6000.00' })

describe('cashflowGroups', () => {
  it('G-1: Current accounts, Savings, Credit cards, in that order, with subtotals', () => {
    const groups = cashflowGroups([card, savings, current], '6000.00')
    expect(groups.map((g) => [g.heading, g.subtotal.text])).toEqual([
      ['Current accounts', '£1,000.00'],
      ['Savings', '£2,000.00'],
      ['Credit cards', '£6,000.00 owed'],
    ])
    expect(groups[2].subtotal.tone).toBe('text-warn')
  })

  it('G-6: an empty family has no group; excluded accounts are not listed', () => {
    expect(cashflowGroups([current], 0).map((g) => g.heading)).toEqual(['Current accounts'])
    expect(cashflowGroups([savings, card], '6000').map((g) => g.heading)).toEqual(['Savings', 'Credit cards'])
    expect(cashflowGroups([acc({ display_name: 'X', role: 'excluded' })], 0)).toEqual([])
  })

  it('keeps the API order inside a group', () => {
    const second = acc({ display_name: 'Second Current', role: 'spending', current_balance: 5 })
    expect(cashflowGroups([second, current], 0)[0].accounts.map((a) => a.display_name)).toEqual(['Second Current', 'Test Current'])
  })

  it("the Credit cards subtotal is the API's credit owed, not a browser sum", () => {
    const inCredit = acc({ display_name: 'Overpaid', role: 'credit', credit_owed: '-50.00' })
    expect(cashflowGroups([card, inCredit], '6000.00')[0].subtotal.text).toBe('£6,000.00 owed')
  })
})

describe('cardFigure', () => {
  it('G-3: owed carries the word', () => {
    expect(cardFigure('6000.00')).toEqual({ text: '£6,000.00 owed', tone: 'text-warn' })
    expect(cardFigure(0)).toEqual({ text: '£0.00 owed', tone: 'text-warn' })
  })

  it('G-7: in credit reads "in credit", not amber', () => {
    expect(cardFigure('-50')).toEqual({ text: '£50.00 in credit', tone: 'text-pos' })
  })
})

describe('heroSubline', () => {
  it('G-2: counts current and savings only, never cards', () => {
    expect(heroSubline(2)).toBe('across 2 accounts')
    expect(heroSubline(1)).toBe('across 1 account')
    expect(heroSubline(0)).toBe('no current or savings accounts connected')
  })
})
