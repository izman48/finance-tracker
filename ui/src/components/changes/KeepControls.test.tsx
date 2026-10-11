import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import {
  CommitmentKeep,
  SavableNote,
  KeepButton,
  KeepNotice,
  KEEP_CHANGED_TEXT,
  KEEP_FAILED_TEXT,
  KEEP_UNCERTAIN_TEXT,
  type KeepState,
} from './KeepControls'
import { KEEP_PENDING_TEXT } from '../../lib/keep'
import type { Commitment } from '../../types'

// "Keep this change", income scope (ux spec section 9: KP1, KP3-KP7, KP12, KP13).
const noop = () => {}
const idle: KeepState = { keeping: false, failure: null }
const html = (node: JSX.Element) => renderToStaticMarkup(<MemoryRouter>{node}</MemoryRouter>)
const text = (h: string) => h.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'")
const names = (h: string) => [...h.matchAll(/aria-label="([^"]*)"/g)].map((m) => m[1])

const income = (over: Partial<Commitment> = {}): Commitment => ({
  id: 'c1',
  direction: 'income',
  label: 'Salary',
  amount: 1500,
  cadence: 'monthly',
  interval_days: null,
  interval_months: null,
  next_date: '2026-10-28',
  source: 'manual',
  status: 'confirmed',
  account_id: null,
  match_key: null,
  changed_by_claude: { audit_id: 'a2', at: '2026-10-11T09:00:00Z' },
  keep: 'pending',
  keep_audit_ids: ['a1', 'a2'],
  ...over,
})
const row = (c: Commitment, keep = idle, undo = idle) =>
  html(<CommitmentKeep c={c} keep={keep} undo={undo} onKeep={noop} onUndo={noop} />)

describe('KeepButton', () => {
  it('KP1/KP12: Keep this change, named with the label, 44px on mobile', () => {
    const h = html(<KeepButton actionKey="k" label="Salary" state={idle} onKeep={noop} />)
    expect(text(h)).toBe('Keep this change')
    expect(names(h)).toEqual(['Keep this change: Salary'])
    expect(h).toContain('data-action="k"')
    expect(h).toContain('min-h-[44px]')
  })

  it('KP3/KP12: Keeping… while pending, disabled and busy', () => {
    const h = html(<KeepButton actionKey="k" label="Salary" state={{ keeping: true, failure: null }} onKeep={noop} />)
    expect(text(h)).toBe('Keeping…')
    expect(names(h)).toEqual(['Keeping: Salary'])
    expect(h).toMatch(/disabled/)
    expect(h).toContain('aria-busy="true"')
  })

  it('KP5/KP12: Try again after a failure', () => {
    for (const failure of ['other', 'rate', 'unknown'] as const) {
      const h = html(<KeepButton actionKey="k" label="Salary" state={{ keeping: false, failure }} onKeep={noop} />)
      expect(text(h)).toBe('Try again')
      expect(names(h)).toEqual(['Try again: keep Salary'])
      expect(h).not.toMatch(/disabled/)
    }
  })

  it('KP7: no Keep button after a 409', () => {
    expect(html(<KeepButton actionKey="k" label="Salary" state={{ keeping: false, failure: 'changed' }} onKeep={noop} />)).toBe('')
  })
})

describe('KeepNotice', () => {
  it('KP5: an HTTP failure says nothing was changed, with no server text', () => {
    expect(KEEP_FAILED_TEXT).toBe("Couldn't keep this. Nothing was changed. Try again.")
    for (const failure of ['other', 'rate'] as const) {
      const h = html(<KeepNotice alertId="x" failure={failure} />)
      expect(text(h)).toBe(KEEP_FAILED_TEXT)
      expect(h).toContain('role="alert"')
    }
  })

  it('KP6: no answer never claims nothing changed', () => {
    expect(KEEP_UNCERTAIN_TEXT).toBe(
      "Couldn't confirm that. It may have been kept; check this item before you try again.",
    )
    expect(text(html(<KeepNotice alertId="x" failure="unknown" />))).toBe(KEEP_UNCERTAIN_TEXT)
  })

  it('KP7: the 409 text, focusable, with Open commitments', () => {
    const h = html(<KeepNotice alertId="x-alert" failure="changed" />)
    expect(KEEP_CHANGED_TEXT).toBe(
      "Can't keep this: it has changed since Claude made the change. Check its current value first.",
    )
    expect(text(h)).toContain(KEEP_CHANGED_TEXT)
    expect(h).toMatch(/id="x-alert"[^>]*tabindex="-1"|tabindex="-1"[^>]*id="x-alert"/)
    expect(h).toMatch(/<a[^>]*href="\/commitments"[^>]*>Open commitments<\/a>/)
  })

  it('KP4: no failure, no notice, and never the word Kept', () => {
    expect(html(<KeepNotice alertId="x" failure={null} />)).toBe('')
    for (const f of ['changed', 'other', 'unknown'] as const) {
      expect(text(html(<KeepNotice alertId="x" failure={f} />))).not.toContain('Kept')
    }
  })
})

describe('CommitmentKeep (the commitment row, 9.1)', () => {
  it('KP1: pending line, then Keep, then Undo, each named with the label', () => {
    const h = row(income())
    expect(text(h)).toContain(KEEP_PENDING_TEXT)
    expect(names(h)).toEqual(['Keep this change: Salary', 'Undo: Claude’s changes to “Salary”'])
    expect(h.indexOf('Keep this change')).toBeLessThan(h.indexOf('>Undo<'))
  })

  it('9.3: a dismissed income gets the dismissal line, Keep and Undo', () => {
    const h = row(income({ status: 'dismissed' }))
    expect(text(h)).toContain('Claude dismissed this. It still counts in your safe to spend until you keep this change.')
    expect(text(h)).not.toContain(KEEP_PENDING_TEXT)
    expect(names(h)).toEqual(['Keep this change: Salary', 'Undo: Claude’s changes to “Salary”'])
  })

  it('KP1/KP13: nothing once kept, when not held, or on an expense', () => {
    expect(row(income({ keep: 'kept', kept_at: '2026-10-11T10:00:00Z' }))).toBe('')
    expect(row(income({ keep: null }))).toBe('')
    expect(row(income({ direction: 'expense' }))).toBe('')
  })

  it('KP7: a 409 stays readable after the refetch clears keep, with no Keep button', () => {
    const h = row(income({ keep: null }), { keeping: false, failure: 'changed' })
    expect(text(h)).toContain(KEEP_CHANGED_TEXT)
    expect(h).not.toContain('Keep this change')
  })

  it('KP6: an unknown outcome is hidden once the refetch shows it kept', () => {
    expect(row(income({ keep: 'kept' }), { keeping: false, failure: 'unknown' })).toBe('')
  })

  it('Undo on the row: Undoing… while pending; its failures use the undo copy', () => {
    const busy = row(income(), idle, { keeping: true, failure: null })
    expect(names(busy)).toContain('Undoing: Claude’s changes to “Salary”')
    const failed = row(income(), idle, { keeping: false, failure: 'other' })
    expect(text(failed)).toContain("Couldn't undo this. Nothing was changed. Try again.")
    expect(names(failed)).toContain('Try again: undo Claude’s changes to “Salary”')
  })
})

describe('SavableNote (KP10)', () => {
  it('under savable on Cashflow: the total and a Review link to commitments', () => {
    const h = html(<SavableNote total="500.00" />)
    expect(text(h)).toBe("£500.00 of income Claude added isn't counted in savable until you keep it. Review")
    expect(h).toMatch(/<a[^>]*href="\/commitments"[^>]*>Review<\/a>/)
    expect(h).toContain('text-xs text-slate-400')
    expect(h).not.toContain('role=')
  })

  it('absent when nothing is held back', () => {
    expect(html(<SavableNote total="0.00" />)).toBe('')
    expect(html(<SavableNote total={undefined} />)).toBe('')
  })
})
