import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import LiabilityRow, { LoansLoadError, BothCountedNotice } from './LiabilityRow'
import type { Asset, Liability } from '../../services/api'

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

// T-12-7b part 2 (ux T-12-1 "Mortgage and equity").
describe('a mortgage row', () => {
  const house = { id: 'h1', name: 'Sample House', asset_type: 'property' } as Asset
  const mortgage = (over: Partial<Liability> = {}) => loan({
    kind: 'mortgage', lender: 'Sample Bank', balance: '120000.00', current_balance: '120000.00', apr: '4.50',
    payment: '780.00', end_date: null, payoff_date: '2051-11-01', property_asset_id: 'h1',
    linked_commitment: { id: 'c1', label: 'Sample Bank mortgage payment' }, ...over,
  })
  const row = (l: Liability) => renderToStaticMarkup(<LiabilityRow liability={l} properties={[house]} onChooseProperty={() => {}} />)

  it('"{lender} mortgage", its line 2 with the property, Bill linked, and the debt', () => {
    const h = row(mortgage())
    const t = text(h)
    expect(t).toContain('Sample Bank mortgage')
    expect(t).toContain('Mortgage · 4.5% APR · £780 a month · final payment Nov 2051 · for Sample House')
    expect(h).toMatch(/class="chip-info[^"]*"[^>]*>Bill linked</)
    expect(t).toContain('−£120,000')
    expect(t).not.toContain('Choose a property')
  })
  it('no property: a separate Choose a property button, never inside the row button', () => {
    const h = row(mortgage({ property_asset_id: null }))
    expect(text(h)).toContain('Choose a property')
    expect(h).not.toMatch(/<button[^>]*>(?:(?!<\/button>).)*<button/)
  })
})

describe('a plan whose card has gone (T-12-7b, ux "Plans": card disconnected)', () => {
  it('shows under Loans and finance as debt, with a Card disconnected chip', async () => {
    const { DisconnectedPlanRow } = await import('./LiabilityRow')
    const h = renderToStaticMarkup(<DisconnectedPlanRow plan={{
      id: 'p1', card_account_id: null, card_name: null, name: 'Laptop plan', balance: '800.00', instalment: '100.00',
      fee: '5.00', instalments_remaining: 8, next_date: '2026-11-04', final_date: '2027-06-04', monthly_total: '105.00',
      in_net_worth: true, provider_confirmed: false,
    }} />)
    const t = h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
    expect(t).toContain('Laptop plan')
    expect(t).toContain('£105 a month · 8 payments to go')
    expect(h).toMatch(/class="chip-warn[^"]*"[^>]*>Card disconnected</)
    expect(t).toContain('−£800')
  })

  it('offers Remove (eng-a on #241): a paid-off plan whose card has gone would otherwise count forever', async () => {
    const { DisconnectedPlanRow } = await import('./LiabilityRow')
    const h = renderToStaticMarkup(<DisconnectedPlanRow onRemove={() => {}} plan={{
      id: 'p1', card_account_id: null, card_name: null, name: 'Laptop plan', balance: '800.00', instalment: '100.00',
      fee: '5.00', instalments_remaining: 8, next_date: '2026-11-04', final_date: '2027-06-04', monthly_total: '105.00',
      in_net_worth: true, provider_confirmed: false,
    }} />)
    expect(h).toMatch(/<button[^>]*aria-label="Remove Laptop plan"[^>]*>Remove<\/button>/)
  })
})

describe('LiabilityRow end-date warning (T-12-12)', () => {
  it('a payoff well after the final payment entered says so, in words', () => {
    const h = html(loan())
    expect(text(h)).toContain('nilu works out the last payment as Aug 2031, after the final payment you entered (Jan 2031). Check the APR and payment.')
    expect(h).toMatch(/class="[^"]*text-warn[^"]*"[^>]*>nilu works out/)
  })
  it('no warning when they agree', () => {
    expect(text(html(loan({ payoff_date: '2031-01-01' })))).not.toContain('nilu works out')
  })
})
