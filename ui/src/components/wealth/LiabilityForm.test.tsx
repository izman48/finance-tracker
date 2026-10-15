import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { LiabilityFormView, type LiabilityFormViewProps } from './LiabilityForm'
import { blankForm } from '../../lib/liabilityForm'
import type { Asset } from '../../services/api'

// ux T-10-0 B.3/B.4 and Accessibility. Static markup, like the other component tests.
const carLoan = { id: 'asset-7', name: 'Car loan', asset_type: 'loan', valuations: [{ id: 'v', value: '-9000', valued_at: '2026-09-01' }] } as Asset
const props = (over: Partial<LiabilityFormViewProps> = {}): LiabilityFormViewProps => ({
  mode: 'add', form: blankForm('2026-10-14'), errors: {}, message: null, saving: false, notFound: false,
  replaceable: [], candidates: null, choice: null, linkedLabel: null, stale: false,
  onChange: () => {}, onChoose: () => {}, onBack: () => {}, onSubmit: () => {}, onCancel: () => {},
  onDelete: () => {}, onOtherDebt: () => {}, ...over,
})
const html = (p: LiabilityFormViewProps) => renderToStaticMarkup(<LiabilityFormView {...p} />)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/\s+/g, ' ').trim()

describe('LiabilityFormView', () => {
  it('is a labelled modal dialog with the fields in the spec order', () => {
    const h = html(props())
    expect(h).toContain('role="dialog"')
    expect(h).toContain('aria-modal="true"')
    expect(h).toMatch(/aria-labelledby="liability-form-title"/)
    const t = text(h)
    const order = ['Type', 'Lender', 'Balance (£)', 'Balance as of', 'APR (%)', 'Payment (£)', 'How often', 'Started on', 'Final payment (optional)', 'I repay this loan irregularly']
    const at = order.map((label) => t.indexOf(label))
    expect(at.every((i) => i >= 0)).toBe(true)
    expect(at).toEqual([...at].sort((a, b) => a - b))
    expect(t).toContain('Add a loan or finance')
    expect(t).toContain("Enter what your lender's statement says. nilu works out the rest.")
  })

  it('money and APR inputs use a decimal keypad and no autocomplete', () => {
    const h = html(props())
    expect(h).toMatch(/id="liability-balance"[^>]*inputmode="decimal"|inputmode="decimal"[^>]*id="liability-balance"/i)
    expect(h).not.toContain('type="number"')
  })

  it('the replace picker shows only when a loan-type asset exists (add mode)', () => {
    expect(text(html(props()))).not.toContain('Replace an entry on your balance sheet')
    const t = text(html(props({ replaceable: [carLoan] })))
    expect(t).toContain('Replace an entry on your balance sheet')
    expect(t).toContain('Car loan · −£9,000')
  })

  it('field errors sit under their field, linked and marked invalid; the summary is an alert', () => {
    const h = html(props({ errors: { payment: 'Enter the payment amount, or tick "I repay this loan irregularly".' }, message: 'Some details are not valid. Check the fields marked below and try again.' }))
    expect(h).toMatch(/id="liability-payment"[^>]*aria-invalid="true"/)
    expect(h).toMatch(/aria-describedby="[^"]*liability-payment-error/)
    expect(h).toContain('role="alert"')
  })

  it('edit mode: title, Delete loan, the linked bill line and the stale banner', () => {
    const t = text(html(props({ mode: 'edit', form: { ...blankForm('2026-10-14'), lender: 'Test Lender', balance_as_of: '2026-06-03' }, linkedLabel: 'Test Lender', stale: true })))
    expect(t).toContain('Edit Test Lender')
    expect(t).toContain('Delete loan')
    expect(t).toContain('Linked to your bill "Test Lender".')
    expect(t).toContain("Enter today's balance from your lender so the figures stay right.")
  })

  it('L-16: a missing loan shows the message and disables Save', () => {
    const h = html(props({ mode: 'edit', notFound: true }))
    expect(text(h)).toContain('We could not find this loan. Close this window and reload the page.')
    expect(h).toMatch(/<button[^>]*disabled=""[^>]*>Save<\/button>/)
  })

  it('L-11: the bill picker lists the candidates and None of these; Add loan waits for a choice', () => {
    const candidates = [{ id: 'c1', label: 'LOAN DD', amount: '200.00', cadence: 'monthly', interval_days: null, next_date: '2026-11-28' }]
    const h = html(props({ candidates, form: { ...blankForm('2026-10-14'), payment: '200.00' } }))
    const t = text(h)
    expect(t).toContain('Which bill is this loan?')
    expect(t).toContain('LOAN DD')
    expect(t).toContain('None of these. Add a new bill for this loan.')
    expect(h).toContain('<fieldset')
    expect(h).toMatch(/<button[^>]*disabled=""[^>]*>Add loan<\/button>/)
    expect(html(props({ candidates, choice: 'c1' }))).not.toMatch(/<button[^>]*disabled=""[^>]*>Add loan<\/button>/)
  })

  it('while saving, Save reads Saving… and inputs are disabled', () => {
    const h = html(props({ saving: true }))
    expect(text(h)).toContain('Saving…')
    expect(h).toMatch(/id="liability-lender"[^>]*disabled=""/)
  })

  it('L-17: the lender renders as text', () => {
    const h = html(props({ mode: 'edit', form: { ...blankForm('2026-10-14'), lender: '<img src=x onerror=alert(1)>' } }))
    expect(h).not.toContain('<img')
  })
})

// T-12-7b part 2 (ux T-12-1 "Mortgage and equity").
describe('LiabilityFormView: a mortgage', () => {
  const house = { id: 'h1', name: 'Sample House', asset_type: 'property', valuations: [] } as unknown as Asset
  const flat = { id: 'h2', name: 'Sample Flat', asset_type: 'property', valuations: [] } as unknown as Asset
  const mortgageForm = (over = {}) => ({ ...blankForm('2026-10-14'), kind: 'mortgage' as const, ...over })

  it('Type offers Mortgage', () => {
    expect(html(props())).toMatch(/<option value="mortgage">Mortgage<\/option>/)
  })
  it('titles: Add a mortgage / Edit mortgage', () => {
    expect(text(html(props({ form: mortgageForm() })))).toContain('Add a mortgage')
    expect(text(html(props({ mode: 'edit', form: mortgageForm({ lender: 'Sample Bank' }) })))).toContain('Edit mortgage')
  })
  it('a Property select (the properties plus None) with its help, after Type, only for a mortgage', () => {
    const h = html(props({ form: mortgageForm({ property_asset_id: 'h1' }), properties: [house, flat] }))
    expect(h).toMatch(/<label class="label" for="liability-property">Property<\/label>/)
    expect(h).toMatch(/<option value="">None<\/option><option value="h1" selected="">Sample House<\/option><option value="h2">Sample Flat<\/option>/)
    expect(text(h)).toContain('Used to show your equity. It does not change your net worth.')
    expect(text(h).indexOf('Type')).toBeLessThan(text(h).indexOf('Property'))
    expect(html(props({ properties: [house] }))).not.toContain('liability-property')
  })
})

describe('choosing Mortgage preselects the only property', () => {
  it('one property: picked; two: left for the user', async () => {
    const { kindChange } = await import('../../lib/liabilityForm')
    const house = { id: 'h1' } as Asset
    expect(kindChange('mortgage', '', [house])).toEqual({ kind: 'mortgage', property_asset_id: 'h1' })
    expect(kindChange('mortgage', '', [house, { id: 'h2' } as Asset])).toEqual({ kind: 'mortgage' })
    expect(kindChange('mortgage', 'h2', [house])).toEqual({ kind: 'mortgage' })
    expect(kindChange('loan', 'h1', [house])).toEqual({ kind: 'loan' })
  })
})
