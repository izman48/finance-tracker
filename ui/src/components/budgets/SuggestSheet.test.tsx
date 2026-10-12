import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SuggestSheet, { type SuggestSheetProps } from './SuggestSheet'
import { suggestion } from '../../lib/budgets.fixtures'

// The Suggest sheet (concept 4.1, 9; T-09-6). Node suite: static markup of each state.
const noop = () => {}
const loaded = {
  suggestions: [
    suggestion(),
    suggestion({ category: 'Dining at home', last_cycles: [], suggested_limit: null, reason: 'not_enough_history' }),
  ],
  commitment_covered: ['Rent'],
}
const html = (props: Partial<SuggestSheetProps>) =>
  renderToStaticMarkup(
    <SuggestSheet load={{ status: 'ready', data: loaded }} saving={false} failure={null} onCancel={noop} onRetry={noop} onSave={noop} {...props} />,
  )
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')

describe('SuggestSheet', () => {
  it('a labelled dialog with the helper text', () => {
    const h = html({})
    expect(h).toMatch(/role="dialog"[^>]*aria-modal="true"[^>]*aria-labelledby="([^"]+)"/)
    expect(text(h)).toContain('Suggest budgets')
    expect(text(h)).toContain("Based on the middle of your last 3 pay cycles, so one big shop doesn't inflate it.")
  })

  it('a row: ticked, its history, and a labelled numeric limit prefilled with the suggestion', () => {
    const h = html({})
    expect(text(h)).toContain('Last 3 cycles: £276 · £291 · £262')
    const tag = (label: string) => h.match(new RegExp(`<input[^>]*aria-label="${label}"[^>]*>`))?.[0] ?? ''
    expect(tag('Include Groceries')).toMatch(/type="checkbox"/)
    expect(tag('Include Groceries')).toMatch(/checked=""/)
    const limit = tag('Limit for Groceries \\(£\\)')
    expect(limit).toMatch(/inputMode="numeric"/)
    expect(limit).toMatch(/value="280"/)
  })

  it('not enough history: said plainly, no limit and nothing to tick (never invented)', () => {
    const h = html({})
    expect(text(h)).toContain('Dining at home')
    expect(text(h)).toContain('Not enough history yet')
    expect(h).not.toContain('Limit for Dining at home')
    expect(h).not.toContain('Include Dining at home')
  })

  it('commitment-covered categories are explained, not offered', () => {
    expect(text(html({}))).toContain('Bills and rent are left out because your commitments already cover them.')
  })

  it('Cancel and Save budgets; while saving, Saving… and both disabled', () => {
    expect(html({})).toMatch(/>Cancel<\/button>/)
    expect(html({})).toMatch(/>Save budgets<\/button>/)
    const busy = html({ saving: true })
    expect(busy).toMatch(/<button[^>]*disabled=""[^>]*>Cancel<\/button>/)
    expect(busy).toMatch(/<button[^>]*disabled=""[^>]*aria-busy="true"[^>]*>Saving…<\/button>/)
  })

  it('a save error says nothing was changed; no answer never does', () => {
    expect(text(html({ failure: 'other' }))).toContain("Couldn't save the budgets. Nothing was changed. Try again.")
    const unknown = text(html({ failure: 'unknown' }))
    expect(unknown).toContain("Couldn't confirm that. Your budgets may have been saved; check them before you try again.")
    expect(unknown).not.toContain('Nothing was changed')
  })

  it('loading and load error', () => {
    expect(text(html({ load: { status: 'loading' } }))).toContain('Working out suggestions…')
    const failed = html({ load: { status: 'error' } })
    expect(failed).toContain('role="alert"')
    expect(text(failed)).toContain("Couldn't work out suggestions. Nothing was changed. Try again.")
  })

  it('a category is text, never markup', () => {
    const data = { suggestions: [suggestion({ category: '<b>x</b>' })], commitment_covered: [] }
    expect(html({ load: { status: 'ready', data } })).toContain('&lt;b&gt;x&lt;/b&gt;')
  })
})
