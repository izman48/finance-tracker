import { describe, expect, it } from 'vitest'
import { BALANCE_SHEET_GROUPS } from './balanceSheet'

// ux T-10-13 Wealth: the two families named the same way everywhere (G-8, G-9).
describe('balance sheet groups', () => {
  const labels = BALANCE_SHEET_GROUPS.map((g) => g.label)

  it('G-8: current accounts and credit cards, never "Cash" or "Owed"', () => {
    expect(labels).toEqual([
      'Current accounts', 'Savings', 'Investments & pensions', 'Property', 'Other', 'Credit cards',
      'Loans and finance', 'Excluded',
    ])
    expect(labels).not.toContain('Cash')
    expect(labels).not.toContain('Owed')
  })

  it('G-9: credit cards sit directly above loans and finance', () => {
    expect(labels.indexOf('Loans and finance') - labels.indexOf('Credit cards')).toBe(1)
  })
})
