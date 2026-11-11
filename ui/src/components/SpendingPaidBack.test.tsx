import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { CategoryPaidBack, PaidBackChip, PaidBackLine } from './SpendingPaidBack'
import type { Transaction } from '../types'

// Spending's purchases view, paid back (T-03-6 P12; PRD Screens 4, ACs 3, 32). Static markup.
const tx = (over: Partial<Transaction> = {}): Transaction => ({
  id: 'd1', account_id: 'a1', transaction_type: 'debit', amount: 200, currency: 'GBP', description: 'Pizza Express',
  merchant_name: 'Pizza Express', category: 'Eating out', subcategory: null, is_recurring: false, is_commitment: false,
  is_financed: false, excluded_reason: null, transaction_date: '2026-11-06T00:00:00Z', ...over,
})
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim()

describe('a spend row', () => {
  it('AC-32: "£110.00 of £200.00 paid back. Counts as £90.00." with the chip in words', () => {
    const t = tx({ paid_back_amount: '110.00' })
    expect(text(renderToStaticMarkup(<PaidBackLine transaction={t} />))).toBe('£110.00 of £200.00 paid back. Counts as £90.00.')
    expect(text(renderToStaticMarkup(<PaidBackChip transaction={t} />))).toBe('£110 paid back')
  })

  it('AC-3: a later repayment reads "£150.00 of £200.00 paid back"', () => {
    expect(text(renderToStaticMarkup(<PaidBackLine transaction={tx({ paid_back_amount: '150.00' })} />))).toContain(
      '£150.00 of £200.00 paid back. Counts as £50.00.')
  })

  it('nothing on a spend with nothing paid back, or on a credit', () => {
    for (const t of [tx(), tx({ paid_back_amount: '0.00' }), tx({ transaction_type: 'credit', paid_back_amount: null })]) {
      expect(renderToStaticMarkup(<PaidBackLine transaction={t} />)).toBe('')
      expect(renderToStaticMarkup(<PaidBackChip transaction={t} />)).toBe('')
    }
  })
})

describe('a category, category marks', () => {
  it('the reference line, only above £0', () => {
    expect(text(renderToStaticMarkup(<CategoryPaidBack amount="110.00" />))).toBe('Paid back by others −£110.00')
    expect(renderToStaticMarkup(<CategoryPaidBack amount="0" />)).toBe('')
    expect(renderToStaticMarkup(<CategoryPaidBack amount={undefined} />)).toBe('')
  })
})
