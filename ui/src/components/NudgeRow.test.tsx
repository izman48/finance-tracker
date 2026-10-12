import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import NudgeRow from './NudgeRow'

// One nudge in the Cashflow feed. A failed server dismissal says so (ux on #161).
const nudge = { id: 'budget-1b0c2d3e-0000-4000-8000-000000000001', body: 'Eating out has reached its £150 budget.' }

describe('NudgeRow', () => {
  it('shows the body and a Dismiss button', () => {
    const h = renderToStaticMarkup(<NudgeRow nudge={nudge} dismissFailed={false} onDismiss={() => {}} />)
    expect(h).toContain('Eating out has reached its £150 budget.')
    expect(h).toContain('>Dismiss</button>')
    expect(h).not.toContain('role="alert"')
  })

  it('a failed dismissal: our own line, announced, and the nudge stays', () => {
    const h = renderToStaticMarkup(<NudgeRow nudge={nudge} dismissFailed onDismiss={() => {}} />)
    expect(h).toMatch(/role="alert"[^>]*>Couldn&#x27;t dismiss that\. Try again\.</)
    expect(h).toContain('Eating out has reached its £150 budget.')
  })
})
