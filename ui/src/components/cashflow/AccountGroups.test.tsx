import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import AccountGroups from './AccountGroups'
import type { SummaryAccount } from '../../types'

// ux T-10-13 Cashflow (G-1, G-3..G-5, G-13, G-14). Synthetic fixture.
const acc = (over: Partial<SummaryAccount>) =>
  ({
    id: 'id', provider_name: 'Test Bank', current_balance: 0, credit_owed: null,
    repayment_cadence: 'monthly', repayment_strategy: 'full_balance', ...over,
  }) as SummaryAccount
const current = acc({ id: 'a1', display_name: 'Test Current', role: 'spending', current_balance: 1000 })
const savings = acc({ id: 'a2', display_name: 'Test Savings', role: 'savings', current_balance: 2000 })
const card = (statement: SummaryAccount['statement'] | 'absent', over: Partial<SummaryAccount> = {}) => {
  const a = acc({ id: 'c1', display_name: 'Test Card', role: 'credit', credit_owed: '6000.00', ...over })
  return statement === 'absent' ? a : { ...a, statement }
}
const html = (accounts: SummaryAccount[]) =>
  renderToStaticMarkup(<MemoryRouter><AccountGroups accounts={accounts} creditOwed="6000.00" /></MemoryRouter>)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/&#x27;/g, "'")
const unpaid = { statement_balance: '5000.00', due_date: '2026-10-31', paid: false, missing: false }
const cardRow = (h: string) => h.slice(h.indexOf('Test Card'))

describe('AccountGroups', () => {
  it('G-14: each family is a section labelled by its h3 heading', () => {
    const h = html([current, savings, card(unpaid)])
    for (const [key, heading] of [['current', 'Current accounts'], ['savings', 'Savings'], ['credit', 'Credit cards']]) {
      expect(h).toContain(`<section aria-labelledby="accounts-${key}"`)
      expect(h).toMatch(new RegExp(`<h3 id="accounts-${key}"[^>]*>${heading}</h3>`))
    }
  })

  it('G-1, G-3: subtotals, and only the card figure says owed', () => {
    const t = text(html([current, savings, card(unpaid)]))
    expect(t).toContain('Current accounts £1,000.00')
    expect(t).toContain('Savings £2,000.00')
    expect(t).toContain('Credit cards £6,000.00 owed')
    expect(t.match(/owed/g)).toHaveLength(2) // the group subtotal and the card row
    expect(t).not.toMatch(/· Credit|· Savings/)
  })

  it('G-4: the card line 2 per statement state', () => {
    expect(text(cardRow(html([card(unpaid)])))).toContain('Statement £5,000.00 · due 31 Oct')
    const paid = cardRow(html([card({ ...unpaid, paid: true })]))
    expect(text(paid)).toContain('Statement paid')
    expect(paid).toMatch(/class="chip-pos[^"]*">Paid</)
    const missing = cardRow(html([card({ ...unpaid, missing: true })]))
    expect(text(missing)).toContain('Statement was due 31 Oct')
    expect(missing).toMatch(/<a[^>]*class="[^"]*chip-warn[^"]*"[^>]*>Add new<\/a>/)
    expect(cardRow(html([card(null)]))).toMatch(/<a[^>]*>Add statement<\/a>/)
    const absent = text(cardRow(html([card('absent')])))
    expect(absent).toContain('Test Bank')
    expect(absent).not.toContain('Statement')
  })

  it('G-5: Add statement and Add new open that card’s settings, as their own controls', () => {
    for (const s of [null, { ...unpaid, missing: true }]) {
      const h = html([card(s)])
      expect(h).toMatch(/<a[^>]*href="\/networth\?settings=c1"/)
      expect(h).toMatch(/<a[^>]*min-h-\[44px\]/)
    }
  })

  it('G-13: names render as text', () => {
    const h = html([acc({ id: 'x', display_name: '<b>x</b>', role: 'spending', provider_name: '<i>p</i>' })])
    expect(h).not.toContain('<b>')
    expect(h).not.toContain('<i>')
    expect(h).toContain('&lt;b&gt;x&lt;/b&gt;')
  })

  it('T-10-12: a card with no repayment set up keeps its notice, with a 44px link', () => {
    const h = html([card(null, { repayment_cadence: null, repayment_strategy: null })])
    expect(text(h)).toContain("Repayment not set up, so this card isn't in your forecast")
    expect(h).toMatch(/<a[^>]*min-h-\[44px\][^>]*>Set up repayment<\/a>/)
  })

  it('sub-lines use slate-400, never slate-500', () => {
    expect(html([current, savings, card(unpaid)])).not.toContain('text-slate-500')
  })
})
