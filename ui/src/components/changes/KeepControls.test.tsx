import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import {
  KeepButton,
  KeepNotice,
  KEEP_CHANGED_TEXT,
  KEEP_FAILED_TEXT,
  KEEP_UNCERTAIN_TEXT,
  type KeepState,
} from './KeepControls'

// "Keep this change", income scope (ux spec section 9: KP3-KP7, KP12).
const noop = () => {}
const idle: KeepState = { keeping: false, failure: null }
const html = (node: JSX.Element) => renderToStaticMarkup(<MemoryRouter>{node}</MemoryRouter>)
const text = (h: string) => h.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'")
const names = (h: string) => [...h.matchAll(/aria-label="([^"]*)"/g)].map((m) => m[1])

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
