import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import NetWorthKey, { type NetWorthKeyProps } from './NetWorthKey'
import { keyRows } from '../../lib/netWorthLines'

// ux T-11-2 N-1..N-7, X-1, X-2. Static markup like the other component tests.
const point = {
  date: '2026-10-15', bank: '0', assets: '0', net_worth: '98900.00',
  cash: '10900.00', investments: '28000.00', property: '250000.00', debt: '190000.00',
}
const props = (over: Partial<NetWorthKeyProps> = {}): NetWorthKeyProps => ({
  rows: keyRows(point, true), netWorth: 98900, shown: [], includeInvestments: true, hasInvestments: true,
  announcement: '', onToggle: () => {}, onIncludeInvestments: () => {}, ...over,
})
const html = (p: NetWorthKeyProps) => renderToStaticMarkup(<NetWorthKey {...p} />)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

describe('NetWorthKey', () => {
  it('N-1 a labelled group with Cash, Investments, Property, Debt, then Net worth always shown', () => {
    const h = html(props())
    expect(h).toMatch(/role="group"[^>]*aria-labelledby="nw-key-heading"/)
    expect(text(h)).toMatch(/Show on graph .*Cash .*£10,900 .*Investments .*£28,000 .*Property .*£250,000 .*Debt .*−£190,000 .*Net worth .*£98,900 .*Always shown/)
  })

  it('N-3 a row is a button with aria-pressed and Show / Hide', () => {
    const h = html(props({ shown: ['investments'] }))
    expect(h).toMatch(/aria-pressed="true"[^>]*aria-label="Investments, £28,000, line shown"/)
    expect(h).toMatch(/aria-pressed="false"[^>]*aria-label="Cash, £10,900, line hidden"/)
    expect((h.match(/aria-pressed=/g) ?? []).length).toBe(4)  // Net worth is not a button
  })

  it('N-4 unticked: Investments reads Not included and is not a switch', () => {
    const h = html(props({ rows: keyRows(point, false), netWorth: 70900, includeInvestments: false }))
    expect(text(h)).toMatch(/Investments .*£28,000 .*Not included/)
    expect(text(h)).toMatch(/Net worth without investments .*£70,900/)
    expect((h.match(/aria-pressed=/g) ?? []).length).toBe(3)
    expect(h).toMatch(/type="checkbox"(?![^>]*checked)/)
  })

  it('N-5 no investments: no tick box', () => {
    expect(html(props({ hasInvestments: false }))).not.toContain('type="checkbox"')
    expect(text(html(props()))).toContain('Include investments in net worth')
  })

  it('X-2 a polite live region carries the announcement', () => {
    expect(html(props({ announcement: 'Investments line shown.' }))).toMatch(/aria-live="polite"[^>]*>Investments line shown\./)
  })

  it('X-4 no slate-500 text', () => {
    expect(html(props())).not.toContain('text-slate-500')
  })
})
