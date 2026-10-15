import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ForecastTooltip } from '../ForecastChart'

// P2: the forecast's event list names a linked loan bill by its lender,
// matched on the event's commitment id as Coming up does (sec on #198).
const point = (label: string, commitment_id: string | null, amount = -200, kind = 'expense') => ({
  payload: { date: '2026-11-01', balance: 1000, events: [{ label, amount, kind, commitment_id }] },
})
const html = (label: string, id: string | null, lenders: Map<string, string>, amount?: number, kind?: string) =>
  renderToStaticMarkup(<ForecastTooltip active payload={[point(label, id, amount, kind)]} lenders={lenders} />)

describe('ForecastTooltip', () => {
  const lenders = new Map([['c1', 'Lender A']])

  it('renames the linked bill by commitment id and leaves other events alone', () => {
    expect(html('LOAN DD', 'c1', lenders)).toContain('Lender A loan payment')
    expect(html('Gym', 'c2', lenders)).toContain('Gym')
    expect(html('LOAN DD', null, lenders)).toContain('LOAN DD')
    expect(html('LOAN DD', 'c1', new Map())).toContain('LOAN DD')
  })

  it('a different bill with the same label as the loan bill keeps its own label', () => {
    expect(html('LOAN DD', 'c9', lenders)).not.toContain('loan payment')
  })

  it('never renames income', () => {
    expect(html('LOAN DD', 'c1', lenders, 200, 'income')).not.toContain('loan payment')
  })

  it('renders the lender as text', () => {
    const h = html('LOAN DD', 'c1', new Map([['c1', '<b>x</b>']]))
    expect(h).not.toContain('<b>')
    expect(h).toContain('&lt;b&gt;x&lt;/b&gt; loan payment')
  })
})

describe('ForecastTooltip projected card bill (T-12-7a, ux C-6)', () => {
  const bill = (projected: boolean) => renderToStaticMarkup(
    <ForecastTooltip active payload={[{ payload: { date: '2026-10-31', balance: 1000, events: [{ label: 'Amex Gold', amount: -640, kind: 'repayment', projected }] } }]} />,
  )
  it('a projected bill says so; a real one reads as before', () => {
    expect(bill(true)).toContain('Amex Gold bill (projected)')
    expect(bill(false)).not.toContain('(projected)')
  })
})
