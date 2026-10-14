import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { RepaymentNotSetUpBanner, RepaymentNotSetUpLine, RepaymentNotSetUpNotice } from './RepaymentNotSetUp'
import type { SummaryAccount } from '../../types'

// T-10-12 (owner D8): Home and Cashflow name the card and link to its settings.
const card = { id: 'c1', display_name: 'Test Card', role: 'credit', credit_owed: '250.00' } as SummaryAccount
const html = (node: JSX.Element) => renderToStaticMarkup(<MemoryRouter>{node}</MemoryRouter>)
const text = (h: string) => h.replace(/<[^>]+>/g, '')
const NOTICE = "Repayment not set up, so this card isn't in your forecast"

describe('RepaymentNotSetUpLine (Cashflow card row)', () => {
  it('says the card is not in the forecast and links to its settings', () => {
    const h = html(<RepaymentNotSetUpLine account={card} />)
    expect(text(h).replace(/&#x27;/g, "'")).toContain(NOTICE)
    expect(h).toMatch(/<a[^>]*href="\/networth\?settings=c1"[^>]*>Set up repayment<\/a>/)
  })
})

describe('RepaymentNotSetUpBanner (Home)', () => {
  it('is one link per card, naming the card, to its settings', () => {
    const h = html(<RepaymentNotSetUpBanner account={card} />)
    expect(h.match(/<a /g)).toHaveLength(1)
    expect(h).toMatch(/<a[^>]*href="\/networth\?settings=c1"/)
    const t = text(h).replace(/&#x27;/g, "'")
    expect(t).toContain('Test Card')
    expect(t).toContain(NOTICE)
  })
})

describe('RepaymentNotSetUpNotice (Home; ux on #193: one notice, not a stack)', () => {
  const second = { ...card, id: 'c2', display_name: 'Other Card' } as SummaryAccount

  it('shows nothing with no such card, and the single-card row for one', () => {
    expect(html(<RepaymentNotSetUpNotice accounts={[]} />)).toBe('')
    expect(html(<RepaymentNotSetUpNotice accounts={[card]} />)).toBe(html(<RepaymentNotSetUpBanner account={card} />))
  })

  it('lists several cards in one notice, each a 44px link to its settings', () => {
    const h = html(<RepaymentNotSetUpNotice accounts={[card, second]} />)
    expect(h.match(/class="[^"]*\bcard\b/g)).toHaveLength(1)
    expect(text(h).replace(/&#x27;/g, "'")).toContain("Repayment not set up on 2 cards, so they aren't in your forecast")
    const first = h.match(/<a[^>]*href="\/networth\?settings=c1"[^>]*>Set up (<!-- -->)?Test Card<\/a>/)![0]
    expect(first).toContain('min-h-[44px]')
    expect(h).toMatch(/<a[^>]*href="\/networth\?settings=c2"[^>]*>Set up (<!-- -->)?Other Card<\/a>/)
  })
})
