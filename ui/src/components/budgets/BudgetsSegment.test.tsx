import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import BudgetsSegment from './BudgetsSegment'

// This cycle / Past cycles (concept 14: "Past cycles", not "History").
describe('BudgetsSegment', () => {
  it('two buttons, the current one pressed and styled active', () => {
    const h = renderToStaticMarkup(<BudgetsSegment value="past" onChange={() => {}} />)
    expect(h).toContain('role="group" aria-label="Budgets period"')
    expect(h).toMatch(/aria-pressed="false" class="seg[^"]*"[^>]*>This cycle</)
    expect(h).toMatch(/aria-pressed="true" class="seg-active[^"]*"[^>]*>Past cycles</)
    expect(h).not.toContain('>History<')
  })
})
