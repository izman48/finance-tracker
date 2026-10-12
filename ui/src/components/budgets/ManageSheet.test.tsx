import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import ManageSheet, { LimitEditor, type ManageSheetProps } from './ManageSheet'
import { budget, budgetsResponse } from '../../lib/budgets.fixtures'
import { LIMIT_ERROR } from '../../lib/budgets'

// Manage budgets (concept section 13, BM1-BM3, BM9, BM10, BM12, BM13; T-09-7a). Static markup.
const noop = () => {}
const resolved = () => Promise.resolve()
const data = budgetsResponse({
  budgets: [
    budget({ changed_by_claude: { audit_id: 'a1', at: '2026-10-12T09:00:00Z' } }),
    budget({ id: 'p', category: 'Hobbies', paused: true, status: null, limit_pounds: 40, spent: '0' }),
  ],
})
const html = (props: Partial<ManageSheetProps> = {}) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <ManageSheet
        data={data}
        categories={['Groceries', 'Hobbies', 'Transport']}
        message={null}
        onClose={noop}
        onAdd={resolved}
        onSaveLimit={resolved}
        onTogglePause={resolved}
        onRemove={resolved}
        onSaveAll={resolved}
        onSuggest={() => Promise.resolve({ suggestions: [], commitment_covered: [] })}
        {...props}
      />
    </MemoryRouter>,
  )
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')
const names = (h: string) => [...h.matchAll(/aria-label="([^"]*)"/g)].map((m) => m[1])

describe('ManageSheet', () => {
  it('a labelled dialog with the cycle subtitle', () => {
    const h = html()
    expect(h).toMatch(/role="dialog"[^>]*aria-labelledby/)
    expect(text(h)).toContain('Manage budgets')
    expect(text(h)).toContain('Pay cycle 14 Oct to 11 Nov. Changes apply to this cycle and the ones after.')
  })

  it('BM1: every budget, active and paused, in the order given', () => {
    const t = text(html())
    expect(t.indexOf('Groceries')).toBeLessThan(t.indexOf('Hobbies'))
    expect(t).toContain('£212 of £300 this cycle')
    expect(t).toContain('Paused')
    expect(t).toContain('Not tracked, not in your totals')
  })

  it('row controls are named with the category (label in name)', () => {
    const n = names(html())
    for (const name of ['Edit Groceries', 'Pause Groceries', 'Remove Groceries', 'Edit Hobbies', 'Resume Hobbies', 'Remove Hobbies']) {
      expect(n).toContain(name)
    }
  })

  it('header actions: + Add budget, Suggest again, Edit all', () => {
    const h = html()
    expect(h).toMatch(/<button[^>]*>\+ Add budget<\/button>/)
    expect(h).toMatch(/<button[^>]*>Suggest again<\/button>/)
    expect(h).toMatch(/<button[^>]*>Edit all<\/button>/)
  })

  it('BM10: the Changed by Claude chip, and the footer link to the Changes screen; no Keep control', () => {
    const h = html()
    expect(h).toMatch(/href="\/changes#change-a1"/)
    expect(text(h)).toContain('Claude changed 1 budget on 12 Oct')
    expect(h).toMatch(/<a[^>]*href="\/changes"[^>]*>See changes made by Claude →<\/a>/)
    expect(text(h)).not.toContain('Keep this change')
  })

  it('a write message shows as an alert, from the spec copy only', () => {
    const h = html({ message: "Couldn't save your budgets. Nothing was changed. Try again." })
    expect(h).toMatch(/role="alert"[^>]*>Couldn&#x27;t save your budgets. Nothing was changed. Try again./)
  })

  it('BM13: a category is text', () => {
    const d = budgetsResponse({ budgets: [budget({ category: '<img src=x onerror=alert(1)>' })] })
    expect(html({ data: d })).not.toContain('<img')
  })

  it('BM12: controls are 44px tall on a phone', () => {
    expect(html()).toMatch(/aria-label="Pause Groceries"[^>]*class="[^"]*min-h-\[44px\]|class="[^"]*min-h-\[44px\][^"]*"[^>]*aria-label="Pause Groceries"/)
  })
})

describe('LimitEditor', () => {
  const editor = (props: Partial<Parameters<typeof LimitEditor>[0]> = {}) =>
    renderToStaticMarkup(<LimitEditor category="Groceries" value="300" error={null} saving={false} onChange={noop} onSave={noop} onCancel={noop} {...props} />)

  it('a labelled numeric field with Save and Cancel', () => {
    const h = editor()
    expect(h).toMatch(/aria-label="Limit for Groceries \(£\)"/)
    expect(h).toMatch(/inputMode="numeric"/)
    expect(h).toMatch(/>Save<\/button>/)
    expect(h).toMatch(/>Cancel<\/button>/)
  })

  it('BM3: the error as an alert, the field marked invalid', () => {
    const h = editor({ error: LIMIT_ERROR })
    expect(h).toContain('role="alert"')
    expect(h).toContain('aria-invalid="true"')
  })

  it('saving: Saving… and disabled', () => {
    expect(editor({ saving: true })).toMatch(/<button[^>]*disabled=""[^>]*aria-busy="true"[^>]*>Saving…<\/button>/)
  })
})
