import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { BudgetLegend, BudgetStrip } from './BudgetStrip'
import type { BudgetProjection } from '../../lib/budgetProjection'

// The payday strip and legend (concept 12; BC1, BC4-BC6, BC10, BC12). Static markup.
const p = (over: Partial<BudgetProjection> = {}): BudgetProjection => ({
  payday: '2026-10-24', scheduled_balance: '480.00', stick_to_budgets_balance: '52.00', current_pace_balance: '-30.00',
  headroom: '52.00', difference: '0.00', series: [{ date: '2026-10-23', balance: '52.00' }], ...over,
})
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')

describe('BudgetStrip', () => {
  it('BC1/BC10: the title and three figures as text', () => {
    const t = text(renderToStaticMarkup(<BudgetStrip projection={p()} />))
    expect(t).toContain('Your balance on payday (24 Oct), before your pay arrives')
    for (const s of ['Scheduled only', '£480', 'If you stick to your budgets', '£52', 'At your current pace', '−£30']) {
      expect(t).toContain(s)
    }
  })

  it('BC5: only a figure below £0 uses text-neg', () => {
    const h = renderToStaticMarkup(<BudgetStrip projection={p()} />)
    expect((h.match(/text-neg/g) ?? []).length).toBe(1)
    expect(h).toMatch(/text-neg[^>]*>−£30</)
  })

  it('the footnote always; BC12 only when the figures differ; BC6 only on a dip', () => {
    const plain = text(renderToStaticMarkup(<BudgetStrip projection={p()} />))
    expect(plain).toContain('The dotted line stops at payday')
    expect(plain).not.toContain('Your headroom on Spending')
    expect(plain).not.toContain('dip below £0')
    const both = text(renderToStaticMarkup(
      <BudgetStrip projection={p({ difference: '250.00', series: [{ date: '2026-10-22', balance: '-1.00' }] })} />,
    ))
    expect(both).toContain('so they differ by £250.')
    expect(both).toContain('you would dip below £0 on 22 Oct.')
  })

  it('no alarm styling: the dip note is informational', () => {
    const h = renderToStaticMarkup(<BudgetStrip projection={p({ series: [{ date: '2026-10-22', balance: '-1.00' }] })} />)
    expect(h).not.toContain('banner-err')
    expect(h).not.toContain('role="alert"')
  })
})

describe('BudgetLegend (BC10: pattern and text, not colour alone)', () => {
  it('names both lines with their swatches', () => {
    const h = renderToStaticMarkup(<BudgetLegend />)
    expect(text(h)).toContain('Scheduled')
    expect(text(h)).toContain('If you spend your budgets')
    expect(h).toContain('border-dotted')
  })
})
