import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import ChangeList from './ChangeList'
import { addEvent, item } from '../../lib/changes.fixtures'
import type { AuditItem } from '../../lib/changes'

// C4, C5, C10, C11, C14, C15 (ux spec nilu-s08-claude-changes.md 1.3-1.5).
// The suite runs in node (no DOM library), so read the static markup.

const render = (items: AuditItem[]) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <ChangeList items={items} accountNames={{}} />
    </MemoryRouter>,
  )
const text = (html: string) =>
  html.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')

describe('ChangeList', () => {
  it('C4: rows in API order, each an li with its id, title, lines and meta', () => {
    const html = render([item({ id: 'x1' }), addEvent('expense', { id: 'x2' }), item({ id: 'x3', target_label: 'Gym' })])
    expect(html).toContain('<ul aria-label="Changes made by Claude"')
    const ids = [...html.matchAll(/<li id="change-([^"]+)"/g)].map((m) => m[1])
    expect(ids).toEqual(['x1', 'x2', 'x3'])
    expect(html).toMatch(/<li id="change-x1"[^>]*tabindex="-1"/)
    expect(html).toMatch(/<time datetime="2026-10-12T14:32:00Z">/i)
    expect(text(html)).toContain('via Claude Desktop')
    expect(text(html)).toContain('connected 3 Oct')
  })

  it('C5: before → after with a screen-reader "changed to"', () => {
    const t = text(render([item()]))
    expect(t).toContain('Changed the commitment “Streaming”')
    expect(t).toContain('Amount')
    expect(t).toContain('£10.99')
    expect(t).toContain('£12.99')
    expect(t).toContain(' changed to ')
    const html = render([item()])
    expect(html).toContain('<span aria-hidden="true"> → </span>')
    expect(html).toContain('<span class="sr-only"> changed to </span>')
  })

  it('C5: expected income says it is not counted', () => {
    const t = text(render([addEvent('income')]))
    expect(t).toContain('Counted in safe to spend')
    expect(t).toContain('No, not until it arrives')
  })

  it('C10: a row undone on the server shows the Undone chip with its date', () => {
    const html = render([item({ undone_at: '2026-10-13T08:00:00Z' })])
    expect(text(html)).toContain('Undone 13 Oct')
    expect(html).toMatch(/class="chip[^"]*"[^>]*>Undone 13 Oct/)
  })

  it('C11: consecutive rows with one batch id are grouped under a header', () => {
    const rows = [item({ id: 'b1', batch_id: 'B' }), item({ id: 'b2', batch_id: 'B', tool: 'dismiss_commitment' })]
    const t = text(render(rows))
    expect(t).toContain('One change, 2 steps')
    expect(t).toContain('Undoing only one step leaves the rest in place.')
    const allUndone = rows.map((r) => ({ ...r, undone_at: '2026-10-13T08:00:00Z' }))
    expect(text(render(allUndone))).not.toContain('Undoing only one step')
  })

  it('C14: labels and client names are text, never markup', () => {
    const evil = '<img src=x onerror=alert(1)>'
    const html = render([item({ target_label: evil, client_name: evil })])
    expect(html).not.toContain('<img')
    expect(text(html)).toContain(`“${evil}”`)
  })

  it('C15: plain "via" text, no badge, the full cleaned name in title', () => {
    const html = render([item({ client_name: 'Claude‮ Desktop' })])
    expect(html).toMatch(/<span title="Claude Desktop">via Claude Desktop<\/span>/)
    expect(text(render([item({ client_name: null })]))).toContain('via an unnamed app')
    expect(html).not.toMatch(/<svg|chip-info|badge/)
  })

  it('uses no low-contrast slate shades', () => {
    expect(render([item(), addEvent('income', { id: 'z' })])).not.toMatch(/text-slate-(500|600|700)/)
  })
})
