import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ForecastTooltip } from '../ForecastChart'

// P2: the forecast's event list names a linked loan bill by its lender.
const point = (label: string, amount = -200, kind = 'expense') => ({
  payload: { date: '2026-11-01', balance: 1000, events: [{ label, amount, kind }] },
})
const html = (label: string, lenders: Map<string, string>, amount?: number, kind?: string) =>
  renderToStaticMarkup(<ForecastTooltip active payload={[point(label, amount, kind)]} lenders={lenders} />)

describe('ForecastTooltip', () => {
  it('renames a linked loan bill and leaves other events alone', () => {
    const lenders = new Map([['LOAN DD', 'Lender A']])
    expect(html('LOAN DD', lenders)).toContain('Lender A loan payment')
    expect(html('Gym', lenders)).toContain('Gym')
    expect(html('LOAN DD', lenders, 200, 'income')).not.toContain('loan payment')
    expect(html('LOAN DD', new Map())).toContain('LOAN DD')
  })

  it('renders the lender as text', () => {
    const h = html('LOAN DD', new Map([['LOAN DD', '<b>x</b>']]))
    expect(h).not.toContain('<b>')
    expect(h).toContain('&lt;b&gt;x&lt;/b&gt; loan payment')
  })
})
