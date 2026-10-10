import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import ChangesView, { type ChangesViewProps } from './ChangesView'
import { item } from '../../lib/changes.fixtures'

// Page states, ux spec 1.6: C2, C3, C12, C13.
const noop = () => {}
const render = (over: Partial<ChangesViewProps>) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <ChangesView
        status="ready"
        items={[]}
        accountNames={{}}
        hasOlder={false}
        older="idle"
        onRetry={noop}
        onOlder={noop}
        {...over}
      />
    </MemoryRouter>,
  )
const text = (html: string) => html.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'")

describe('ChangesView', () => {
  it('always shows the heading (focus target), subtitle and footnote', () => {
    const html = render({})
    expect(html).toMatch(/<h1[^>]*tabindex="-1"[^>]*>Changes made by Claude<\/h1>/)
    expect(text(html)).toContain(
      'Everything an AI assistant changed in your planned events and commitments. You can undo any change here.',
    )
    expect(text(html)).toContain('"via" names are chosen by the app that connected. nilu. doesn\'t check them.'.replace(/"/g, '&quot;'))
  })

  it('C2: loading shows 3 skeleton rows, a busy list and a status message, nothing else', () => {
    const html = render({ status: 'loading' })
    expect(html.match(/data-skeleton/g)).toHaveLength(3)
    expect(html).toContain('aria-busy="true"')
    expect(html).toMatch(/role="status"[^>]*>Loading changes…/)
    expect(text(html)).not.toContain("Claude hasn't changed anything yet")
    expect(html).not.toContain('id="change-')
  })

  it('C3: empty shows the heading and body, and no Undo', () => {
    const t = text(render({ items: [] }))
    expect(t).toContain("Claude hasn't changed anything yet")
    expect(t).toContain(
      'When you let an AI assistant change your planned events or commitments, every change appears here and you can undo it.',
    )
    expect(t).not.toContain('Undo')
  })

  it('C12: a failed first load shows the spec copy and Try again, in place of the card', () => {
    const html = render({ status: 'error' })
    expect(html).toMatch(/class="banner-err[^"]*"[^>]*role="alert"|role="alert"[^>]*class="banner-err/)
    expect(text(html)).toContain("Couldn't load the changes made by Claude. Nothing has been changed. Try again.")
    expect(text(html)).toContain('Try again')
    expect(html).not.toContain('aria-label="Changes made by Claude"')
  })

  it('C12: while retrying, the button is busy', () => {
    const html = render({ status: 'error', retrying: true })
    expect(html).toMatch(/<button[^>]*disabled[^>]*aria-busy="true"|<button[^>]*aria-busy="true"[^>]*disabled/)
  })

  it('C13: Show older changes appears only with a next cursor', () => {
    expect(text(render({ items: [item()], hasOlder: true }))).toContain('Show older changes')
    expect(text(render({ items: [item()], hasOlder: false }))).not.toContain('Show older changes')
  })

  it('C13: a failed older page keeps the rows and offers Try again', () => {
    const html = render({ items: [item()], hasOlder: true, older: 'error' })
    expect(html).toContain('id="change-a1"')
    expect(text(html)).toContain("Couldn't load older changes. Try again.")
    expect(text(html)).not.toContain('Show older changes')
    expect(html).toMatch(/<button[^>]*>Try again<\/button>/)
  })

  it('touch targets: page buttons are at least 44px tall on mobile', () => {
    const html = render({ status: 'error' }) + render({ items: [item()], hasOlder: true })
    for (const b of html.match(/<button[^>]*>/g) ?? []) expect(b).toContain('min-h-[44px]')
  })

  it('uses no low-contrast slate shades', () => {
    const html = [render({ status: 'loading' }), render({}), render({ status: 'error' })].join('')
    expect(html).not.toMatch(/text-slate-(500|600|700)/)
  })
})
