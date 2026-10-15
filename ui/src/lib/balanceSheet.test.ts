import { describe, expect, it } from 'vitest'
import { accountGroup, assetGroup, BALANCE_SHEET_GROUPS } from './balanceSheet'

// ux T-10-13 Wealth: the two families named the same way everywhere (G-8, G-9).
describe('balance sheet groups', () => {
  const labels = BALANCE_SHEET_GROUPS.map((g) => g.label)

  it('G-8: current accounts and credit cards, never "Cash" or "Owed"', () => {
    expect(labels).toEqual([
      'Current accounts', 'Savings', 'Investments', 'Property', 'Other', 'Credit cards',
      'Loans and finance', 'Excluded',
    ])
    expect(labels).not.toContain('Cash')
    expect(labels).not.toContain('Owed')
  })

  it('G-9: credit cards sit directly above loans and finance', () => {
    expect(labels.indexOf('Loans and finance') - labels.indexOf('Credit cards')).toBe(1)
  })
})

// ux on #192: the Credit cards group holds credit-role bank accounts and
// nothing else, so its subtotal is what's owed on cards.
describe('which group a row lands in', () => {
  it('only a credit-role account goes to Credit cards', () => {
    expect(accountGroup('credit')).toBe('owed')
    for (const role of ['spending', 'savings', 'excluded', 'unknown']) {
      expect(accountGroup(role)).not.toBe('owed')
    }
  })

  it('no manual asset ever goes to Credit cards, whatever its value', () => {
    const types = ['savings', 'isa', 'investment', 'pension', 'crypto', 'property', 'other', 'mortgage', 'loan', 'other_liability', 'unknown']
    for (const type of types) {
      for (const value of [-200, 0, 200]) expect(assetGroup(type, value)).not.toBe('owed')
    }
  })

  it('a negative asset that is not a liability type sits with loans and finance', () => {
    expect(assetGroup('other', -200)).toBe('liabilities')
    expect(assetGroup('savings', -0.01)).toBe('liabilities')
  })

  it('assets keep their own group otherwise', () => {
    expect(assetGroup('isa', 200)).toBe('invest')
    expect(assetGroup('property', 0)).toBe('property')
    expect(assetGroup('loan', 9000)).toBe('liabilities')
    expect(assetGroup('unknown', 5)).toBe('other')
  })
})
