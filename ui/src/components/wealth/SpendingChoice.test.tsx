import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import SpendingChoice, { type SpendingChoiceProps } from './SpendingChoice'

// ux T-10-15a control (P-1, P-2, P-4, P-6). Static markup like the other component tests.
const props = (over: Partial<SpendingChoiceProps> = {}): SpendingChoiceProps => ({
  shown: 'budgets', budgetsAvailable: true, estimate: '', evidence: { text: 'Your budgets: £890 a month.', warn: false },
  onChoose: () => {}, onEstimate: () => {}, ...over,
})
const html = (p: SpendingChoiceProps) =>
  renderToStaticMarkup(<MemoryRouter><SpendingChoice {...p} /></MemoryRouter>)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

describe('SpendingChoice', () => {
  it('a fieldset with legend Everyday spending and two native radios in order', () => {
    const h = html(props())
    expect(h).toContain('<fieldset')
    expect(text(h)).toMatch(/Everyday spending .*My budgets .*Average past spending/)
    expect((h.match(/type="radio"/g) ?? []).length).toBe(2)
  })

  it('P-1 My budgets checked and the evidence line live', () => {
    const h = html(props())
    expect(h).toMatch(/value="budgets"[^>]*checked=""|checked=""[^>]*value="budgets"/)
    expect(h).toMatch(/aria-live="polite"[^>]*>Your budgets: £890 a month\./)
  })

  it('P-2 no active budgets: My budgets disabled with "Add a budget to use this." linking budgets', () => {
    const h = html(props({ shown: 'average', budgetsAvailable: false }))
    expect(h).toMatch(/value="budgets"[^>]*disabled=""|disabled=""[^>]*value="budgets"/)
    expect(text(h)).toContain('Add a budget to use this.')
    expect(h).toContain('href="/insights?section=budgets"')
  })

  it('P-4 the estimate box only under Average, with use measured when filled', () => {
    expect(html(props())).not.toContain('id="spending-estimate"')
    const h = html(props({ shown: 'average', estimate: '900' }))
    expect(h).toContain('id="spending-estimate"')
    expect(text(h)).toContain('use measured')
  })

  it('two choices only: My budgets and Average past spending; no None (owner, T-12-0)', () => {
    const h = html(props())
    expect((h.match(/type="radio"/g) ?? []).length).toBe(2)
    expect(text(h)).not.toContain('None')
  })

  it('secondary text is slate-400', () => {
    expect(html(props())).not.toContain('text-slate-500')
  })
})
