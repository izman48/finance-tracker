import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import InvestmentRow from './InvestmentRow'
import type { Asset } from '../../services/api'

// One row in Wealth's Investments group (ux T-11-2 I-1, I-5, X-1). Static markup; synthetic figures.
const now = new Date('2026-10-11T12:00:00Z').getTime()
const asset = (over: Partial<Asset> = {}): Asset => ({
  id: 'a1', name: 'Test ISA', asset_type: 'isa', assumed_growth_pct: '7', monthly_contribution: null,
  linked_commitment: { id: 'c1', label: 'Test ISA contribution', amount: '1000.00' },
  valuations: [{ id: 'v1', value: '18000.00', valued_at: '2026-10-01' }], ...over,
})
const html = (a: Asset) => renderToStaticMarkup(<InvestmentRow asset={a} now={now} onOpen={() => {}} onUpdateValue={() => {}} />)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('InvestmentRow', () => {
  it('I-1: name, line, Bill linked chip and value', () => {
    const t = text(html(asset()))
    expect(t).toContain('Test ISA')
    expect(t).toContain('ISA · 7% a year · £1,000 a month')
    expect(t).toContain('Bill linked')
    expect(t).toContain('£18,000')
  })
  it('no chip without a linked bill', () => {
    expect(text(html(asset({ linked_commitment: null, monthly_contribution: '250' })))).not.toContain('Bill linked')
  })
  it('the row button and the Update value button are siblings, not nested (X-1)', () => {
    const h = html(asset())
    expect((h.match(/<button/g) ?? []).length).toBe(2)
    expect(h).toMatch(/<\/button><button[^>]*>Update value<\/button>/)
    expect(h).toContain('id="investment-row-a1"')
    expect(h).toContain('id="investment-update-a1"')
  })
  it('a value older than 30 days makes Update value a warning chip', () => {
    expect(html(asset())).toMatch(/<button[^>]*class="[^"]*chip(?!-warn)[^"]*"[^>]*>Update value/)
    const old = asset({ valuations: [{ id: 'v', value: '1', valued_at: '2026-08-01' }] })
    expect(html(old)).toMatch(/<button[^>]*class="[^"]*chip-warn[^"]*"[^>]*>Update value/)
  })
  it('shows how old the value is in words', () => {
    expect(text(html(asset()))).toContain('updated 10 days ago')
  })
  it('I-5: a name with markup renders as text', () => {
    const h = html(asset({ name: '<img src=x onerror=alert(1)>' }))
    expect(h).not.toContain('<img')
    expect(h).toContain('&lt;img')
  })
})
