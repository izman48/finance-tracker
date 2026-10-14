import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import RepaymentWarnings from './RepaymentWarnings'

// ux T-10-0 A.6, C-17, C-19. Synthetic values.
const interest = { code: 'interest_cost' as const, values: { monthly_interest: '71.95', apr: '20.00' } }

describe('RepaymentWarnings', () => {
  it('a live region with each warning prefixed "Warning:" for assistive tech and a decorative icon', () => {
    const h = renderToStaticMarkup(<RepaymentWarnings warnings={[interest]} codes={['interest_cost']} providerName="Test Bank" />)
    expect(h).toMatch(/aria-live="polite"/)
    expect(h).toMatch(/<span class="sr-only">Warning: <\/span>/)
    expect(h).toMatch(/aria-hidden="true"/)
    expect(h).toContain('That is about £71.95 a month')
  })

  it('shows only the codes for its control, and keeps the live region even when empty', () => {
    const h = renderToStaticMarkup(<RepaymentWarnings warnings={[interest]} codes={['late_fee_risk']} providerName="Test Bank" />)
    expect(h).toMatch(/aria-live="polite"/)
    expect(h).not.toContain('Warning:')
  })

  it('C-19: a provider name with markup is shown as text', () => {
    const h = renderToStaticMarkup(<RepaymentWarnings warnings={[interest]} codes={['interest_cost']} providerName="<b>x</b>" />)
    expect(h).not.toContain('<b>x</b>')
    expect(h).toContain('&lt;b&gt;x&lt;/b&gt;')
  })
})
