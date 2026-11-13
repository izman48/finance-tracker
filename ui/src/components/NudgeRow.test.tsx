import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import NudgeRow from './NudgeRow'
import { focusTargetAfter } from '../lib/nudgeFocus'

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

// "Will go over" (T-24-5; spec nudge copy and states).
describe('NudgeRow with a title and Raise to', () => {
  const willGoOver = {
    id: 'budget-1b0c2d3e-0000-4000-8000-000000000002', title: 'Eating out will go over',
    body: '£94 left, but Meal kit has £128 still to come before payday. Raise the budget or expect to be £34 over.',
    raise: { label: 'Raise to £550', budgetId: 'b-1', newLimit: 550, category: 'Eating out' },
  }
  const row = (extra: Partial<Parameters<typeof NudgeRow>[0]> = {}) =>
    renderToStaticMarkup(<NudgeRow nudge={willGoOver} dismissFailed={false} onDismiss={() => {}} onRaise={() => {}} {...extra} />)

  it('the title, the body and Raise to before Dismiss', () => {
    const h = row()
    expect(h).toMatch(/<p[^>]*class="[^"]*font-semibold[^"]*"[^>]*>Eating out will go over<\/p>/)
    expect(h).toContain('£94 left, but Meal kit has £128 still to come before payday.')
    expect(h.indexOf('>Raise to £550</button>')).toBeGreaterThan(0)
    expect(h.indexOf('>Raise to £550</button>')).toBeLessThan(h.indexOf('>Dismiss</button>'))
  })

  it('busy: "Raising…", disabled', () => {
    expect(row({ raising: true })).toMatch(/<button[^>]*disabled=""[^>]*>Raising…<\/button>/)
  })

  it('a failed raise says nothing changed, as an alert, and the nudge stays', () => {
    const h = row({ raiseFailed: true })
    expect(h).toMatch(/role="alert"[^>]*>Couldn&#x27;t raise the budget\. Nothing was changed\. Try again\.</)
    expect(h).toContain('Eating out will go over')
  })

  it('a label from bank text renders as text', () => {
    const h = row({ nudge: { ...willGoOver, body: '<img src=x onerror=alert(1)> has £5 still to come' } })
    expect(h).not.toContain('<img')
  })

  it('on phones the buttons get their own row under the text (ux on #302, mockup E1)', () => {
    const h = row()
    expect(h).toMatch(/<span class="[^"]*w-full sm:w-auto[^"]*"><button[^>]*>Raise to £550/)
    expect(h).toContain(`data-nudge="${willGoOver.id}"`)
  })
})

describe('focus after a nudge leaves (ux on #302)', () => {
  it('the next remaining nudge, else the one before, else the page heading', () => {
    expect(focusTargetAfter(['a', 'b', 'c'], 'a')).toBe('b')
    expect(focusTargetAfter(['a', 'b', 'c'], 'c')).toBe('b')
    expect(focusTargetAfter(['a'], 'a')).toBeNull()
  })
})
