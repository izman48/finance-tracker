import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CardRow from './CardRow'
import type { SummaryAccount } from '../../types'
import { dateDayMonth } from '../../lib/format'

// ux T-10-13 Wealth card rows (G-4, G-5, G-7, G-13, G-14). Synthetic fixture.
const card = (over: Partial<SummaryAccount> = {}): SummaryAccount => ({
  id: 'card-1', display_name: 'Test Card', provider_name: 'Test Bank', account_type: 'CREDIT_CARD', role: 'credit',
  current_balance: 6000, credit_owed: '6000.00', overdraft_limit: null, repayment_cadence: null, repayment_day: null,
  repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: null, repayment_fixed_amount: null,
  repayment_installments: null, pay_from_account_id: null,
  statement: { statement_balance: '5000.00', due_date: '2026-10-31', paid: false, missing: false }, ...over,
})
const html = (a: SummaryAccount) => renderToStaticMarkup(<CardRow account={a} onOpen={() => {}} />)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim()

describe('Wealth card row', () => {
  it('G-4 unpaid: provider, then the statement and due date; the figure is debt, announced as owed', () => {
    const t = text(html(card()))
    expect(t).toContain(`Test Bank · Statement £5,000.00 · due ${dateDayMonth('2026-10-31')}`)
    expect(t).toContain('−£6,000 owed')
  })

  it('G-4 paid: provider · Statement paid with a Paid chip', () => {
    const h = html(card({ statement: { statement_balance: '5000.00', due_date: '2026-10-31', paid: true, missing: false } }))
    expect(text(h)).toContain('Test Bank · Statement paid')
    expect(h).toMatch(/class="chip-pos[^"]*"[^>]*>Paid</)
  })

  it('G-4/G-5 due date passed: the text, and Add new as its own button after the row button', () => {
    const h = html(card({ statement: { statement_balance: '5000.00', due_date: '2026-10-31', paid: false, missing: true } }))
    expect(text(h)).toContain(`Statement was due ${dateDayMonth('2026-10-31')}`)
    expect(h).toMatch(/<\/button>\s*<button[^>]*class="chip-warn[^"]*"[^>]*>Add new<\/button>/)
  })

  it('G-4/G-5 no statement entered: an Add statement button, not nested in the row button', () => {
    const h = html(card({ statement: null }))
    expect(h).toMatch(/<\/button>\s*<button[^>]*>Add statement<\/button>/)
    expect(text(h)).toContain('Test Bank')
  })

  it('G-4 no statement data: the provider alone', () => {
    const t = text(html(card({ statement: undefined })))
    expect(t).toContain('Test Bank')
    expect(t).not.toContain('Statement')
    expect(t).not.toContain('Add statement')
  })

  it('G-7 a card in credit reads "in credit", not amber', () => {
    const h = html(card({ credit_owed: '-50.00', statement: undefined }))
    expect(text(h)).toContain('£50 in credit')
    expect(h).not.toContain('text-warn')
  })

  it('G-13 names render as text', () => {
    expect(html(card({ display_name: '<img src=x onerror=alert(1)>' }))).not.toContain('<img')
  })

  it('secondary text is slate-400, never slate-500', () => {
    expect(html(card())).not.toContain('text-slate-500')
  })
})
