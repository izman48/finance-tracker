import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import ClaudeMarker, { NOT_COUNTED_TEXT } from './ClaudeMarker'

// ux spec section 2 (M1, M4).
const html = (auditId: string) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <ClaudeMarker auditId={auditId} />
    </MemoryRouter>,
  )

describe('ClaudeMarker', () => {
  it('M1: links to its row on the changes screen, with the spec label', () => {
    const h = html('a1')
    expect(h).toMatch(/<a[^>]*href="\/changes#change-a1"/)
    expect(h).toContain('aria-label="Changed by Claude. See what changed."')
    expect(h).toContain('chip-info')
    expect(h.replace(/<[^>]+>/g, '')).toBe('Changed by Claude')
  })

  it('the hit area is 44px on mobile, 24px or more elsewhere', () => {
    expect(html('a1')).toMatch(/<a[^>]*class="[^"]*min-h-\[44px\][^"]*sm:min-h-\[24px\]/)
  })

  it('an id that is not a plain token never reaches the link', () => {
    expect(html('a1"><img src=x>')).not.toContain('<img')
  })

  it('M4: the not-counted sentence is the spec copy', () => {
    expect(NOT_COUNTED_TEXT).toBe('Not counted in your safe to spend until it arrives.')
  })
})
