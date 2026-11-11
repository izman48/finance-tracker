import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { PaidBackView, type PaidBackViewProps } from './PaidBackSection'
import { nextUndoAfter } from '../lib/paidBack'
import type { PaidBackMark, Transaction } from '../types'

// The transaction sheet's "Paid back" section (T-03-6; PRD Screens 1-2, ACs 29-32, 34, 35). Static markup.
const tx = (over: Partial<Transaction> = {}): Transaction => ({
  id: 't1', account_id: 'a1', transaction_type: 'credit', amount: 100, currency: 'GBP', description: 'SAM',
  merchant_name: 'SAM', category: null, subcategory: null, is_recurring: false, is_commitment: false,
  is_financed: false, excluded_reason: null, transaction_date: '2026-11-08T00:00:00Z', ...over,
})
const mark = (over: Partial<PaidBackMark> = {}): PaidBackMark => ({
  mark_id: 'm1', credit_id: 't1', spend_id: 'd1', category: null, amount: '60.00', label: 'Sam £60.00, Pizza Express',
  created_via: 'mcp', applied: true, cycle_closed: false, audit_id: 'a9', payer: 'SAM', against: 'Pizza Express',
  credit_date: '2026-11-08', spend_date: '2026-11-06', ...over,
})
const html = (props: Partial<PaidBackViewProps>) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <PaidBackView transaction={tx()} undo={{}} onUndo={() => {}} {...props} />
    </MemoryRouter>,
  )
const text = (h: string) =>
  h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim()

describe('PaidBackView, credit sheet', () => {
  it('AC-31: no marks, no section', () => {
    expect(html({ transaction: tx({ paid_back_marks: [] }) })).toBe('')
    expect(html({})).toBe('')
  })

  it('AC-31: two marks, each with its Undo; the unmarked part in the footer', () => {
    const marks = [mark(), mark({ mark_id: 'm2', category: 'Eating out', spend_id: null, amount: '30.00', against: 'Eating out', spend_date: null, audit_id: 'a10' })]
    const h = html({ transaction: tx({ paid_back_marks: marks }) })
    const t = text(h)
    expect(h).toMatch(/<h4[^>]*id="paid-back-heading"[^>]*>Paid back<\/h4>/)
    expect(t).toContain('£60.00 for Pizza Express, 6 Nov')
    expect(t).toContain('£30.00 against Eating out')
    expect(t).toContain('£10.00 of £100.00 not marked.')
    expect(h).toContain('aria-label="Undo: mark £60.00 for Pizza Express"') // AC-35
    expect(h).toContain('aria-label="Undo: mark £30.00 against Eating out"')
    expect(h).toContain('href="/changes#change-a9"')
  })

  it('AC-31: fully marked', () => {
    const t = text(html({ transaction: tx({ paid_back_marks: [mark({ amount: '100.00' })] }) }))
    expect(t).toContain('All of this payment is marked paid back.')
  })

  it('AC-29: a mark whose spend is no longer spending says it is not applied', () => {
    const t = text(html({ transaction: tx({ paid_back_marks: [mark({ applied: false })] }) }))
    expect(t).toContain('£60.00 for Pizza Express. Not applied: that purchase is not counted as spending.')
  })

  it('AC-30: a credit set to a transfer keeps its mark and says so', () => {
    const t = text(html({ transaction: tx({ counts_as_override: 'transfer', paid_back_marks: [mark()] }) }))
    expect(t).toContain('Counted as a transfer, and also marked paid back.')
  })

  it('a mark made in the app has no Undo here', () => {
    expect(html({ transaction: tx({ paid_back_marks: [mark({ audit_id: null, created_via: 'web' })] }) })).not.toContain('Undo')
  })

  it('falls back to the label without the spend name and date', () => {
    const t = text(html({ transaction: tx({ paid_back_marks: [mark({ payer: null, against: null, spend_date: null })] }) }))
    expect(t).toContain('£60.00: Sam £60.00, Pizza Express')
  })
})

describe('PaidBackView, spend sheet', () => {
  const dinner = (marks: PaidBackMark[], paid: string) =>
    tx({ id: 'd1', transaction_type: 'debit', amount: 200, merchant_name: 'Pizza Express', paid_back_amount: paid, paid_back_marks: marks })

  it('AC-32: "£110.00 of £200.00 paid back. Counts as £90.00." and each payer', () => {
    const marks = [mark({ payer: 'Sam' }), mark({ mark_id: 'm2', amount: '50.00', label: 'Jo £50.00, Pizza Express', payer: 'Jo', credit_date: '2026-11-10', audit_id: 'a10' })]
    const t = text(html({ transaction: dinner(marks, '110.00') }))
    expect(t).toContain('£110.00 of £200.00 paid back. Counts as £90.00.')
    expect(t).toContain('£60.00 from Sam, 8 Nov')
    expect(t).toContain('£50.00 from Jo, 10 Nov')
  })

  it('fully paid back, and a closed cycle says its result was not changed', () => {
    const t = text(html({ transaction: dinner([mark({ amount: '200.00', cycle_closed: true, payer: 'Sam' })], '200.00') }))
    expect(t).toContain('£200.00 of £200.00 paid back. Counts as £0.00.')
    expect(t).toContain('Cycle closed: its budget result was not changed.')
  })

  it('undoing: the button reads Undoing…, busy; a failure is an alert', () => {
    const t = dinner([mark({ payer: 'Sam' })], '60.00')
    expect(html({ transaction: t, undo: { m1: { undoing: true, failure: null } } })).toContain('aria-busy="true"')
    expect(html({ transaction: t, undo: { m1: { undoing: false, failure: 'other' } } })).toContain('role="alert"')
  })

  it('labels are text, never markup', () => {
    expect(html({ transaction: tx({ paid_back_marks: [mark({ against: '<img src=x>' })] }) })).not.toContain('<img')
  })
})

describe('after an undo (AC-34; ux on #288)', () => {
  it('focus goes to the next Undo still shown, else to something that stays (null)', () => {
    expect(nextUndoAfter(['a1', 'a2', 'a3'], 'a2')).toBe('a3')
    expect(nextUndoAfter(['a1', 'a2'], 'a2')).toBe('a1')
    expect(nextUndoAfter(['a1'], 'a1')).toBeNull() // the last mark: the section goes, so the sheet title
  })

  it("the Undo's name keeps a spend name with a comma and digits whole", () => {
    const h = html({ transaction: tx({ paid_back_marks: [mark({ against: 'Shop, 2 Go' })] }) })
    expect(h).toContain('aria-label="Undo: mark £60.00 for Shop, 2 Go"')
  })

  it('a credit detected as a transfer also says it is marked', () => {
    const t = text(html({ transaction: tx({ excluded_reason: 'internal_transfer', paid_back_marks: [mark()] }) }))
    expect(t).toContain('Counted as a transfer, and also marked paid back.')
  })
})

