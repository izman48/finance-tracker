import { describe, expect, it } from 'vitest'
import {
  GROUPS, chartRows, headline, keyRows, parseLines, parseIncludeInvestments,
} from './netWorthLines'

// ux T-11-2 fixture: Cash 10,900, Investments 28,000, Property 250,000, Debt 190,000.
const point = {
  date: '2026-10-15', bank: '0', assets: '0', net_worth: '98900.00',
  cash: '10900.00', investments: '28000.00', property: '250000.00', debt: '190000.00',
}

describe('net worth key rows (N-1, N-5, N-6, N-7)', () => {
  it('lists Cash, Investments, Property, Debt with their figures, Debt as minus', () => {
    expect(keyRows(point, true).map((r) => [r.key, r.label, r.value])).toEqual([
      ['cash', 'Cash', 10900], ['investments', 'Investments', 28000],
      ['property', 'Property & other', 250000], ['debt', 'Debt', -190000],
    ])
  })

  it('leaves out a group whose figure is 0, but keeps Debt whenever debt exists', () => {
    const cashOnly = { ...point, investments: '0', property: '0', debt: '0', net_worth: '10900' }
    expect(keyRows(cashOnly, true).map((r) => r.key)).toEqual(['cash'])
    const owing = { ...cashOnly, debt: '50' }
    expect(keyRows(owing, true).map((r) => r.key)).toEqual(['cash', 'debt'])
  })

  it('shows Investments as not included, not a switch, when the box is unticked (N-4)', () => {
    const inv = keyRows(point, false).find((r) => r.key === 'investments')
    expect(inv).toMatchObject({ value: 28000, included: false })
    expect(keyRows(point, true).find((r) => r.key === 'investments')?.included).toBe(true)
  })

  it('has the four groups in the spec order', () => {
    expect(GROUPS.map((g) => g.label)).toEqual(['Cash', 'Investments', 'Property & other', 'Debt'])
  })
})

describe('headline (N-4)', () => {
  it('renames itself without investments', () => {
    expect(headline(true)).toBe('Total net worth')
    expect(headline(false)).toBe('Net worth without investments')
  })
})

describe('stored choices (N-3, N-11, A6)', () => {
  it('keeps only known group keys, and an unknown or broken value gives the default', () => {
    expect(parseLines('["investments","debt"]')).toEqual(['investments', 'debt'])
    expect(parseLines('["investments","boats"]')).toEqual(['investments'])
    expect(parseLines('not json')).toEqual([])
    expect(parseLines(null)).toEqual([])
    expect(parseLines('{"a":1}')).toEqual([])
  })

  it('includes investments unless the box was unticked', () => {
    expect(parseIncludeInvestments(null)).toBe(true)
    expect(parseIncludeInvestments('false')).toBe(false)
    expect(parseIncludeInvestments('true')).toBe(true)
    expect(parseIncludeInvestments('nonsense')).toBe(true)
  })
})

describe('chart rows', () => {
  it('carry net worth and every group, Debt below zero, whatever is shown (N-2)', () => {
    const [row] = chartRows([point], (d) => d)
    expect(row).toEqual({
      date: '2026-10-15', 'Net worth': 98900, Cash: 10900, Investments: 28000, 'Property & other': 250000, Debt: -190000,
    })
  })
})

describe('the key adds up (ux invariant, owner 2026-10-15)', () => {
  it('Cash + Investments + Property & other − Debt = Net worth to the penny', () => {
    const p = { ...point, cash: '10900.37', investments: '28000.01', property: '250000.10', debt: '190000.48',
      net_worth: '98900.00' }
    const sum = keyRows(p, true).reduce((s, r) => s + Math.round(r.value * 100), 0)
    expect(sum).toBe(Math.round(Number(p.net_worth) * 100))
  })

  it('without investments, the included rows add up to the renamed headline', () => {
    const p = { ...point, net_worth: '70900.00' }
    const sum = keyRows(p, false).filter((r) => r.included).reduce((s, r) => s + Math.round(r.value * 100), 0)
    expect(sum).toBe(7090000)
  })
})
