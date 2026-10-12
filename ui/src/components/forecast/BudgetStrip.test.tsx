import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { BudgetLegend, BudgetStrip } from './BudgetStrip'
import type { BudgetProjection } from '../../lib/budgetProjection'

// The payday line and legend, the simple rule (T-09-15; BC1, BC5, BC6, BC10). Static markup.
const p = (over: Partial<BudgetProjection> = {}): BudgetProjection => ({
  payday: '2026-10-24', scheduled_balance: '480.00', after_budgets_balance: '221.00',
  series: [{ date: '2026-10-23', balance: '221.00' }], ...over,
})
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')

describe('BudgetStrip', () => {
  it('one line: payday, scheduled and after budgets, as the API sent them', () => {
    const t = text(renderToStaticMarkup(<BudgetStrip projection={p()} />))
    expect(t).toContain('On payday: £480 scheduled · £221 after budgets')
  })

  it('no pace, headroom or difference anywhere', () => {
    const t = text(renderToStaticMarkup(<BudgetStrip projection={p()} />))
    for (const gone of ['current pace', 'headroom', 'differ', 'stick to', 'stops at payday']) expect(t.toLowerCase()).not.toContain(gone)
  })

  it('BC5: only a figure below £0 uses text-neg', () => {
    expect(renderToStaticMarkup(<BudgetStrip projection={p()} />)).not.toContain('text-neg')
    expect(renderToStaticMarkup(<BudgetStrip projection={p({ after_budgets_balance: '-30.00' })} />)).toMatch(/text-neg[^>]*>−£30</)
  })

  it('BC6: the dip note only on a dip, informational', () => {
    expect(text(renderToStaticMarkup(<BudgetStrip projection={p()} />))).not.toContain('dip below £0')
    const h = renderToStaticMarkup(<BudgetStrip projection={p({ series: [{ date: '2026-10-22', balance: '-1.00' }] })} />)
    expect(text(h)).toContain("If you spend all your budgets, you'd dip below £0 on 22 Oct.")
    expect(h).not.toContain('banner-err')
    expect(h).not.toContain('role="alert"')
  })

  it('the footnote: budgets only, and the trusted figures unchanged', () => {
    expect(text(renderToStaticMarkup(<BudgetStrip projection={p()} />))).toContain(
      "Budgets only: spending outside your budgets isn't included. Safe to spend and “Lowest point” are unchanged.")
  })
})

describe('BudgetLegend (BC10: pattern and text, not colour alone)', () => {
  it('names both lines with their swatches', () => {
    const h = renderToStaticMarkup(<BudgetLegend />)
    expect(text(h)).toContain('Scheduled')
    expect(text(h)).toContain('After your budgets')
    expect(h).toContain('border-dotted')
  })
})
