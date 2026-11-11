import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PaidBackByOthers from './PaidBackByOthers'
import type { NotCounted } from '../../lib/budgets'

// Budgets, "Paid back by others" in Not counted (T-03-6; PRD Screens 3, ACs 4, 32, 34). Static markup.
const base: NotCounted = { commitments: '0.00', transfers: '0.00', card_payoffs: '0.00', financed: '0.00' }
const dinner: NotCounted = {
  ...base,
  paid_back: '110.00',
  paid_back_marks: [
    { label: 'Sam £60.00, Pizza Express', amount: '60.00', against: 'Pizza Express', category: 'Eating out' },
    { label: 'Jo £50.00, Pizza Express', amount: '50.00', against: 'Pizza Express', category: 'Eating out' },
  ],
  paid_back_excess: [],
}
const html = (notCounted: NotCounted, defaultOpen = false) =>
  renderToStaticMarkup(<PaidBackByOthers notCounted={notCounted} defaultOpen={defaultOpen} />)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim()

describe('PaidBackByOthers', () => {
  it('absent with no marks, or at £0', () => {
    expect(html(base)).toBe('')
    expect(html({ ...base, paid_back: '0.00', paid_back_marks: [], paid_back_excess: [] })).toBe('')
  })

  it('AC-32: "Paid back by others £110.00" as a collapsed toggle button (AC-34)', () => {
    const h = html(dinner)
    expect(text(h)).toContain('Paid back by others £110.00')
    expect(h).toMatch(/<button[^>]*aria-expanded="false"[^>]*aria-controls="budgets-paid-back"/)
    expect(text(h)).not.toContain('Sam £60.00')
  })

  it('open: each mark with what it netted and its amount, and the helper text', () => {
    const t = text(html(dinner, true))
    expect(t).toContain('Sam £60.00, Pizza Express Pizza Express £60.00')
    expect(t).toContain('Jo £50.00, Pizza Express Pizza Express £50.00')
    expect(t).toContain("Friends' repayments you marked. They reduce what counts as spending here and are never income.")
    expect(html(dinner, true)).toMatch(/aria-expanded="true"/)
  })

  it('AC-4: the excess is named and never called income', () => {
    const t = text(html({ ...base, paid_back: '40.00', paid_back_marks: [], paid_back_excess: [{ category: 'Eating out', amount: '40.00' }] }))
    expect(t).toContain('Paid back by others £40.00')
    expect(t).toContain("£40.00 was more than you spent in Eating out this cycle. It isn't income.")
  })

  it('labels are text, never markup', () => {
    const h = html({ ...dinner, paid_back_marks: [{ label: '<img src=x>', amount: '1.00', against: '<b>x</b>', category: 'x' }] }, true)
    expect(h).not.toContain('<img')
    expect(h).not.toContain('<b>x')
  })
})
