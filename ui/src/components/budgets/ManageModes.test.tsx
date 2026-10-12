import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { EditAllPanel, SuggestAgainPanel } from './ManageModes'
import { budget, suggestion } from '../../lib/budgets.fixtures'
import { LIMIT_ERROR, suggestDiff } from '../../lib/budgets'

// Edit all (BM4, BM5) and Suggest again (BM6). Static markup.
const noop = () => {}
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ')
const budgets = [budget({ id: 'b1', category: 'Groceries', limit_pounds: 300 }), budget({ id: 'b2', category: 'Eating out', limit_pounds: 150 })]

describe('EditAllPanel', () => {
  const panel = (props: Partial<Parameters<typeof EditAllPanel>[0]> = {}) =>
    renderToStaticMarkup(
      <EditAllPanel budgets={budgets} values={{ b1: '320' }} errors={{}} announced="Total per cycle £470 (was £450)" saving={false} onChange={noop} onBlur={noop} onSave={noop} onCancel={noop} {...props} />,
    )

  it('every limit is a labelled field', () => {
    const h = panel()
    expect(h).toMatch(/aria-label="Limit for Groceries \(£\)"[^>]*value="320"|value="320"[^>]*aria-label="Limit for Groceries \(£\)"/)
    expect(h).toContain('aria-label="Limit for Eating out (£)"')
  })

  it('BM4: the running total, announced politely', () => {
    const h = panel()
    expect(text(h)).toContain('Total per cycle £470 (was £450)')
    expect(h).toMatch(/aria-live="polite"/)
  })

  it('Save changes and Cancel; saving disables both', () => {
    expect(panel()).toMatch(/>Save changes<\/button>/)
    expect(panel({ saving: true })).toMatch(/<button[^>]*disabled=""[^>]*aria-busy="true"[^>]*>Saving…<\/button>/)
  })

  it('BM3: a bad field shows its error, marked invalid', () => {
    const h = panel({ errors: { b1: LIMIT_ERROR } })
    expect(h).toContain('role="alert"')
    expect(h).toContain('aria-invalid="true"')
  })
})

describe('SuggestAgainPanel', () => {
  const diff = suggestDiff(
    [
      suggestion({ category: 'Groceries', suggested_limit: 280, current_limit: 300 }),
      suggestion({ category: 'Eating out', suggested_limit: 150, current_limit: 150 }),
      suggestion({ category: 'Health & beauty', suggested_limit: 40, current_limit: null }),
    ],
    budgets,
  )
  const panel = (props: Partial<Parameters<typeof SuggestAgainPanel>[0]> = {}) =>
    renderToStaticMarkup(
      <SuggestAgainPanel load={{ status: 'ready', diff }} rows={diff.rows} errors={{}} nothing={false} saving={false} onRow={noop} onSave={noop} onCancel={noop} onRetry={noop} {...props} />,
    )

  it('BM6: the summary, the diff lines, New, and the unchanged count', () => {
    const t = text(panel())
    expect(t).toContain('1 change and 1 new budget. Nothing is saved until you press Save.')
    expect(t).toContain('Now £300 → suggested £280')
    expect(t).toContain('Health & beauty')
    expect(t).toContain('New')
    expect(t).toContain('1 unchanged')
    expect(t).not.toContain('Eating out')
  })

  it('rows can be unticked; Save budgets saves nothing until pressed', () => {
    const h = panel()
    expect(h).toContain('aria-label="Include Groceries"')
    expect(h).toMatch(/>Save budgets<\/button>/)
  })

  it('loading and error', () => {
    expect(text(panel({ load: { status: 'loading' } }))).toContain('Working out suggestions…')
    expect(text(panel({ load: { status: 'error' } }))).toContain("Couldn't work out suggestions. Nothing was changed. Try again.")
  })
})
