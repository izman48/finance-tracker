import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import LiabilityRow, { LoansLoadError, BothCountedNotice } from './LiabilityRow'
import type { Liability } from '../../services/api'

// ux T-10-0 B.1/B.2 (Wealth: loans and finance). Synthetic fixture.
const loan = (over: Partial<Liability> = {}): Liability => ({
  id: 'l-a', kind: 'loan', lender: 'Lender A', balance: '9000.00', balance_as_of: '2026-10-01',
  apr: '11.00', payment: '200.00', cadence: 'monthly', start_date: '2026-11-01', end_date: '2031-01-01',
  opted_out: false, current_balance: '9000.00', next_payment_date: '2026-11-01', payments_remaining: 58,
  payoff_date: '2031-08-01', interest_remaining: '2483.22', total_cost: '11483.22', paid_off: false,
  balance_stale: false, linked_commitment: null, link_result: null, ...over,
})
const html = (l: Liability) => renderToStaticMarkup(<LiabilityRow liability={l} />)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim()

describe('LiabilityRow', () => {
  it('L-2: lender, detail line and the balance as debt', () => {
    const t = text(html(loan()))
    expect(t).toContain('Lender A')
    expect(t).toContain('Loan · 11% APR · £200 a month · final payment 1 Jan 2031 · interest left £2,483')
    expect(t).toContain('−£9,000')
  })

  it('L-4: a stale balance shows "Update balance"; a fresh one does not', () => {
    expect(text(html(loan({ balance_stale: true })))).toContain('Update balance')
    expect(text(html(loan()))).not.toContain('Update balance')
  })

  it('L-18: paid off shows the chip and £0', () => {
    const t = text(html(loan({ paid_off: true, current_balance: '0', interest_remaining: '0.00' })))
    expect(t).toContain('Paid off')
    expect(t).toMatch(/£0$/)
  })

  it('L-17: lender text is shown literally, never as markup', () => {
    const h = html(loan({ lender: '<img src=x onerror=alert(1)>' }))
    expect(h).not.toContain('<img')
    expect(h).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })

  it('secondary text meets contrast (slate-400, not slate-500)', () => {
    expect(html(loan())).not.toContain('text-slate-500')
  })
})

describe('LoansLoadError (L-7)', () => {
  it('says net worth may be too high and offers Try again', () => {
    const t = text(renderToStaticMarkup(<LoansLoadError onRetry={() => {}} />))
    expect(t).toBe('We could not load your loans and finance. Your net worth above may be too high until they load. Try again')
  })
})

describe('BothCountedNotice (L-8)', () => {
  it('explains that both count', () => {
    const t = text(renderToStaticMarkup(<BothCountedNotice />))
    expect(t).toBe('You have a loan entered as a balance sheet item and a loan in this list. Both count towards what you owe. If they are the same debt, replace the old entry.')
  })
})
