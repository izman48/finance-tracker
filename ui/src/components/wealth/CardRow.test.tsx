import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CardRow from './CardRow'
import type { SummaryAccount } from '../../types'
import type { CardPlan } from '../../services/api'
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

// T-12-7b (ux T-12-1 "Plans", owner D4): plans indented under their card.
const plan = (over: Partial<CardPlan> = {}): CardPlan => ({
  id: 'p1', card_account_id: 'card-1', card_name: 'Test Card', name: 'Laptop plan', balance: '800.00',
  instalment: '100.00', fee: '5.00', instalments_remaining: 8, next_date: '2026-11-04', final_date: '2027-06-04',
  monthly_total: '105.00', in_net_worth: false, provider_confirmed: false, ...over,
})
const withPlans = (plans: CardPlan[]) => renderToStaticMarkup(<CardRow account={card()} plans={plans} onOpen={() => {}} />)
const decoded = (h: string) => text(h).replace(/&#x27;/g, "'")

describe('Wealth card row with plans', () => {
  it('unconfirmed: a chip on the card, and the plan row with its own chip, why, and what is left (no minus)', () => {
    const h = withPlans([plan()])
    const t = decoded(h)
    expect(h).toMatch(/class="chip-warn[^"]*"[^>]*>1 plan not in net worth yet</)
    expect(h).toContain('aria-label="Plans on Test Card"')
    expect(t).toContain("Laptop plan Not in net worth yet We haven't confirmed whether Test Bank includes plans in the card balance. £105 a month still counts in the card bill. £800 left")
    expect(t).not.toContain('−£800')
  })
  it('confirmed: the card says what it includes; the plan is inside the balance, already counted', () => {
    const t = decoded(withPlans([plan({ provider_confirmed: true, balance: '420.00', monthly_total: '60.00', instalments_remaining: 7 })]))
    expect(t).toContain('· includes 1 plan')
    expect(t).toContain('£60 a month · 7 payments to go · inside the card balance')
    expect(t).toContain('−£420 already counted')
  })
  it('no plans: no list and no plan chip', () => {
    const h = withPlans([])
    expect(h).not.toContain('Plans on')
    expect(h).not.toContain('not in net worth yet')
  })
})
