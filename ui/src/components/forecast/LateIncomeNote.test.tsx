import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import LateIncomeNote from './LateIncomeNote'

describe('LateIncomeNote (L2)', () => {
  it('shows the note in warn with a hidden clock icon', () => {
    const h = renderToStaticMarkup(<LateIncomeNote items={[{ amount: '1203.00' }]} />)
    expect(h).toContain('text-warn')
    expect(h).toContain('aria-hidden="true"')
    expect(h.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'")).toBe(
      "£1,203.00 of expected income is late and isn't counted in this forecast.",
    )
  })

  it('renders nothing when nothing is late (L4)', () => {
    expect(renderToStaticMarkup(<LateIncomeNote items={[]} />)).toBe('')
  })
})
