import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import {
  UndoButton,
  UndoNotice,
  CHANGED_SINCE_TEXT,
  UNDO_FAILED_TEXT,
  UNDO_UNCERTAIN_TEXT,
  RATE_LIMIT_TEXT,
} from './UndoControls'
import { addEvent, item } from '../../lib/changes.fixtures'

// C6-C9 row states (ux spec 1.5). Node suite, static markup.
const noop = () => {}
const html = (node: JSX.Element) => renderToStaticMarkup(<MemoryRouter>{node}</MemoryRouter>)
const text = (h: string) => h.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'")

describe('UndoButton', () => {
  it('available: Undo, labelled with the title, 44px on mobile, full width there', () => {
    const h = html(<UndoButton item={item()} state={{ undoing: false, failure: null }} onUndo={noop} />)
    expect(text(h)).toBe('Undo')
    expect(h).toContain('aria-label="Undo: Changed the commitment “Streaming”"')
    expect(h).toContain('min-h-[44px]')
    expect(h).toContain('w-full')
  })

  it('C6: while pending it reads Undoing…, disabled and busy', () => {
    const h = html(<UndoButton item={item()} state={{ undoing: true, failure: null }} onUndo={noop} />)
    expect(text(h)).toBe('Undoing…')
    expect(h).toMatch(/disabled/)
    expect(h).toContain('aria-busy="true"')
  })

  it('C9: after another failure it reads Try again and is enabled', () => {
    const h = html(<UndoButton item={item()} state={{ undoing: false, failure: 'other' }} onUndo={noop} />)
    expect(text(h)).toBe('Try again')
    expect(h).not.toMatch(/disabled/)
  })

  it('C8 and C10: no button after "changed since", or once undone', () => {
    expect(html(<UndoButton item={item()} state={{ undoing: false, failure: 'changed' }} onUndo={noop} />)).toBe('')
    expect(html(<UndoButton item={item({ undone_at: '2026-10-13T08:00:00Z' })} state={{ undoing: false, failure: null }} onUndo={noop} />)).toBe('')
  })
})

describe('UndoButton accessible name (WCAG 2.5.3, label in name)', () => {
  const label = (h: string) => h.match(/aria-label="([^"]*)"/)?.[1] ?? ''
  it('starts with the visible text in every state', () => {
    const cases = [
      [{ undoing: false, failure: null }, 'Undo', 'Undo: Changed the commitment “Streaming”'],
      [{ undoing: true, failure: null }, 'Undoing…', 'Undoing: Changed the commitment “Streaming”'],
      [{ undoing: false, failure: 'other' }, 'Try again', 'Try again: undo Changed the commitment “Streaming”'],
      [{ undoing: false, failure: 'unknown' }, 'Try again', 'Try again: undo Changed the commitment “Streaming”'],
    ] as const
    for (const [state, visible, name] of cases) {
      const h = html(<UndoButton item={item()} state={state} onUndo={noop} />)
      expect(text(h)).toBe(visible)
      expect(label(h)).toBe(name)
      expect(label(h).toLowerCase().startsWith(visible.replace('…', '').toLowerCase())).toBe(true)
    }
  })
})

describe('UndoNotice', () => {
  it('a timeout or network error does not claim nothing changed (sec)', () => {
    const t = text(html(<UndoNotice item={item()} failure="unknown" />))
    expect(t).toBe(UNDO_UNCERTAIN_TEXT)
    expect(t).not.toContain('Nothing was changed')
  })

  it('once a refetch shows the change undone, a failure notice gives way to the Undone state', () => {
    const undone = item({ undone_at: '2026-10-13T08:00:00Z' })
    expect(html(<UndoNotice item={undone} failure="unknown" />)).toBe('')
    expect(html(<UndoNotice item={undone} failure="other" />)).toBe('')
  })

  it('ux: the Open link is a 44px target on mobile', () => {
    expect(html(<UndoNotice item={item()} failure="changed" />)).toMatch(/<a[^>]*class="[^"]*min-h-\[44px\]/)
  })

  it('C8: the exact changed-since text and a link to where the item lives', () => {
    const h = html(<UndoNotice item={item()} failure="changed" />)
    expect(CHANGED_SINCE_TEXT).toBe(
      "Can't undo this: it has changed since Claude made the change. Check its current value and change it by hand if you need to.",
    )
    expect(h).toContain('role="alert"')
    expect(h).toContain('tabindex="-1"')
    expect(text(h)).toContain(CHANGED_SINCE_TEXT)
    expect(h).toMatch(/<a[^>]*href="\/commitments"[^>]*>Open commitments<\/a>/)
    expect(html(<UndoNotice item={addEvent('expense')} failure="changed" />)).toMatch(
      /<a[^>]*href="\/dashboard"[^>]*>Open planned events<\/a>/,
    )
  })

  it('C9: other failures say nothing was changed; 429 adds the hourly limit', () => {
    expect(UNDO_FAILED_TEXT).toBe("Couldn't undo this. Nothing was changed. Try again.")
    expect(text(html(<UndoNotice item={item()} failure="other" />))).toBe(UNDO_FAILED_TEXT)
    expect(text(html(<UndoNotice item={item()} failure="rate" />))).toBe(UNDO_FAILED_TEXT + RATE_LIMIT_TEXT)
    expect(RATE_LIMIT_TEXT).toBe(" You've reached the hourly limit; try again later.")
  })

  it('C7: no failure, no notice; and never the word Undone', () => {
    expect(html(<UndoNotice item={item()} failure={null} />)).toBe('')
    for (const f of ['changed', 'other', 'rate'] as const) {
      expect(text(html(<UndoNotice item={item()} failure={f} />))).not.toContain('Undone')
    }
  })
})
