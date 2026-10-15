import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import InvestmentGraphView, { type InvestmentGraphViewProps } from './InvestmentGraphView'
import type { InvestmentGraph, InvestmentSeries } from '../../lib/investments'

// The investment graph view (T-11-5; ux T-11-2 G-1..G-10). Static markup; synthetic figures.
const isa: InvestmentSeries = {
  id: 'a1', name: 'Test ISA', kind: 'isa', value_today: '18000.00', value_as_of: '2026-10-15', growth_pct: '7.00',
  monthly_contribution: '1000.00',
  history: [{ date: '2026-04-15', worth: '12000.00' }, { date: '2026-10-15', worth: '18000.00' }],
  forecast: [{ date: '2026-10-15', worth: '18000.00', paid_in: '18000.00' }, { date: '2036-10-15', worth: '206460.00', paid_in: '138000.00' }],
}
const pension: InvestmentSeries = { ...isa, id: 'a2', name: 'Test <b>Pension</b>', kind: 'pension', value_today: '10000.00', growth_pct: '5.00', monthly_contribution: '0.00' }
const graph: InvestmentGraph = {
  as_of: '2026-10-15', months: 120, holdings: [isa, pension],
  total: {
    value_today: '28000.00', monthly_contribution: '1000.00', history: isa.history, forecast: isa.forecast,
    answer: { months: 120, worth_about: '223000', paid_in: '148000' },
  },
}
const props = (over: Partial<InvestmentGraphViewProps> = {}): InvestmentGraphViewProps => ({
  status: 'ready', graph, months: 120, holdingId: null,
  onMonths: () => {}, onHolding: () => {}, onRetry: () => {}, onAdd: () => {}, onEditGrowth: () => {}, ...over,
})
const html = (over: Partial<InvestmentGraphViewProps> = {}) => renderToStaticMarkup(<InvestmentGraphView {...props(over)} />)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('InvestmentGraphView', () => {
  it('title, the answer sentence and the inputs line from the API totals (G-2)', () => {
    const t = text(html())
    expect(t).toContain('Investments')
    expect(t).toContain('In 10 years: worth about £223,000, paid in £148,000')
    expect(t).toContain('2 investments, £28,000 today, £1,000 a month.')
  })

  it('range and selector are native radio groups with their labels (G-10)', () => {
    const h = html()
    expect(text(h)).toContain('Look ahead')
    expect(text(h)).toContain('Which investment')
    for (const label of ['5 years', '10 years', '20 years', '30 years', 'All investments', 'Test ISA']) expect(text(h)).toContain(label)
    expect((h.match(/type="radio"/g) ?? []).length).toBe(4 + 3)
    expect(h).toMatch(/<input[^>]*name="look-ahead"[^>]*checked=""[^>]*value="120"/)
  })

  it('the chart is role img named by the sentence and inputs line (G-10)', () => {
    expect(html()).toContain('role="img" aria-label="In 10 years: worth about £223,000, paid in £148,000. 2 investments, £28,000 today, £1,000 a month."')
  })

  it('a holding name with markup renders as text (I-5)', () => {
    expect(html()).toContain('Test &lt;b&gt;Pension&lt;/b&gt;')
    expect(html()).not.toContain('<b>Pension</b>')
  })

  it('one holding chosen: its own inputs line', () => {
    expect(text(html({ holdingId: 'a1' }))).toContain('£18,000 today, £1,000 a month, 7% a year.')
  })

  it('key names and the dashed/solid explanation', () => {
    const t = text(html())
    expect(t).toContain('Worth')
    expect(t).toContain('Paid in')
    expect(t).toContain('history, then forecast')
  })

  it('the hidden table has Date, Worth, Paid in', () => {
    const t = text(html())
    expect(t).toContain('Date Worth Paid in')
  })

  it('one value only (G-5)', () => {
    const one = { ...graph, holdings: [{ ...isa, history: [isa.history[1]] }], total: { ...graph.total, history: [isa.history[1]] } }
    expect(text(html({ graph: one }))).toContain('Your history starts with your first value. Update the value now and then to see how it moved.')
  })

  it('growth 0 (G-6)', () => {
    const flat = { ...graph, holdings: [{ ...isa, growth_pct: '0.00' }] }
    const t = text(html({ graph: flat, holdingId: 'a1' }))
    expect(t).toContain('Growth is 0% a year, so the forecast is flat.')
    expect(t).toContain('Set a growth rate')
  })

  it('no investments', () => {
    const t = text(html({ graph: { ...graph, holdings: [], total: { ...graph.total, answer: null } } }))
    expect(t).toContain('Add an investment to see its graph.')
    expect(html({ graph: { ...graph, holdings: [] } })).toMatch(/<button[^>]*>Add an investment<\/button>/)
  })

  it('not found (another user\'s id) shows the no investments state (G-8)', () => {
    expect(text(html({ status: 'not_found', graph: null }))).toContain('Add an investment to see its graph.')
  })

  it('a response without holdings (demo mode before T-11-8 serves it) is the empty state, not a crash', () => {
    expect(text(html({ graph: {} as InvestmentGraph }))).toContain('Add an investment to see its graph.')
  })

  it('loading keeps the sentence slot', () => {
    expect(text(html({ status: 'loading', graph: null }))).toContain('Working it out…')
  })

  it('error (G-9)', () => {
    const h = html({ status: 'error', graph: null })
    expect(text(h)).toContain('We could not load this graph. Your values are safe. Try again.')
    expect(h).toMatch(/<button[^>]*>Try again<\/button>/)
  })
})
