import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { RepaymentNotSetUpBanner, RepaymentNotSetUpLine } from './RepaymentNotSetUp'
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
