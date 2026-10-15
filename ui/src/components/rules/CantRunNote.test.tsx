import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CantRunNote from './CantRunNote'

// sec-1 / lead on #248: a stored rule the matching engine can't run says so.
describe('CantRunNote', () => {
  it("shows the chip and the API's reason, in words, not colour alone", () => {
    const h = renderToStaticMarkup(<CantRunNote reason="Look-arounds and back-references aren't supported, so this rule can't run. Edit or delete it." />)
    expect(h).toMatch(/class="chip-warn[^"]*"[^>]*>This rule can(&#x27;|')t run</)
    expect(h).toContain('Look-arounds and back-references')
  })
  it('renders nothing for a rule that runs', () => {
    expect(renderToStaticMarkup(<CantRunNote reason={null} />)).toBe('')
  })
})
