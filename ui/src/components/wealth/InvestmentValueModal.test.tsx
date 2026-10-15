import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import InvestmentValueModal from './InvestmentValueModal'
import type { Asset } from '../../services/api'

// ux T-11-2 "Update value" for an investment (I-2, A8). Static markup; synthetic figures.
const asset: Asset = {
  id: 'a1', name: 'Test <i>ISA</i>', asset_type: 'isa', assumed_growth_pct: '7', monthly_contribution: null,
  valuations: [{ id: 'v1', value: '18000.00', valued_at: '2026-10-01' }],
}
const html = () => renderToStaticMarkup(
  <InvestmentValueModal asset={asset} now={new Date('2026-10-11T12:00:00Z').getTime()} onClose={() => {}} onSaved={() => {}} />,
)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('InvestmentValueModal', () => {
  it('title, the last value line and one labelled field', () => {
    const h = html()
    expect(h).toContain('role="dialog"')
    expect(text(h)).toContain('Update value')
    expect(text(h)).toContain('Test <i>ISA</i>. Last value £18,000, 10 days ago.')
    expect(h).toMatch(/<label[^>]*for="investment-value"[^>]*>Value today \(£\)<\/label>/)
    expect((h.match(/<input/g) ?? []).length).toBe(1)
  })
  it('no "added or withdrawn" field (A8) and the name is text, not markup', () => {
    expect(text(html())).not.toMatch(/added or withdrawn/i)
    expect(html()).not.toContain('<i>ISA</i>')
  })
  it('Cancel and Update value buttons', () => {
    const h = html()
    expect(h).toMatch(/<button[^>]*>Cancel<\/button>/)
    expect(h).toMatch(/<button[^>]*type="submit"[^>]*>Update value<\/button>/)
  })
})
