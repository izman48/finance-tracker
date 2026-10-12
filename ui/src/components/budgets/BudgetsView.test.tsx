import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import BudgetsView, { type BudgetsViewProps } from './BudgetsView'
import { budget, budgetsResponse } from '../../lib/budgets.fixtures'

// Spending > Budgets, this cycle (concept 4.1-4.3, 5, 9; T-09-6). Node suite: static markup.
const noop = () => {}
const html = (props: Partial<BudgetsViewProps>) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <BudgetsView status="ready" data={budgetsResponse()} onRetry={noop} onSuggest={noop} onOpenCategory={noop} {...props} />
    </MemoryRouter>,
  )
const text = (h: string) =>
  h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('BudgetsView', () => {
  it('loading: skeleton bars and "Loading budgets…"', () => {
    const h = html({ status: 'loading', data: null })
    expect(h).toContain('role="status"')
    expect(text(h)).toContain('Loading budgets…')
  })

  it('load error: the spec sentence and Try again, no server text', () => {
    const h = html({ status: 'error', data: null })
    expect(h).toContain('role="alert"')
    expect(text(h)).toContain("Couldn't load your budgets. Your spending is unaffected. Try again.")
    expect(h).toMatch(/<button[^>]*>Try again<\/button>/)
  })

  it('no budgets: the setup card with Suggest budgets and the reassurance line', () => {
    const h = html({ data: budgetsResponse({ budgets: [] }) })
    expect(text(h)).toContain('Set a limit for the things you want to keep an eye on.')
    expect(text(h)).toContain('Budgets follow your pay cycle and never change your safe to spend.')
    expect(h).toMatch(/<button[^>]*class="btn-primary[^"]*"[^>]*>Suggest budgets<\/button>/)
  })

  it('the cycle and what is measured, with the exclusions named', () => {
    const t = text(html({}))
    expect(t).toContain('14 Oct to 11 Nov · 18 days left')
    expect(t).toContain('Measuring purchases. Not counted here: commitments, transfers, card payoffs.')
  })

  it('each row: amounts as text, a labelled meter, status in words, and the pace tick', () => {
    const h = html({})
    expect(text(h)).toContain('Groceries')
    expect(text(h)).toContain('£212 of £300')
    expect(text(h)).toContain('On pace')
    expect(text(h)).toContain('£88 left · 18 days left')
    expect(h).toMatch(/role="meter"[^>]*aria-valuenow="212"[^>]*aria-valuemin="0"[^>]*aria-valuemax="300"[^>]*aria-label="Groceries: £212 of £300, on pace, 18 days left"/)
    expect(h).toMatch(/data-pace[^>]*style="left:calc\(35\.7\d*% - 1px\)"/)
  })

  it('over: "£12 over" outlined, never red', () => {
    const h = html({})
    expect(h).toMatch(/<span class="chip-out">£12 over<\/span>/)
    expect(h).not.toMatch(/text-neg|bg-neg|text-rose|bg-rose/)
  })

  it('a row opens its transactions; the name stays first in the button name', () => {
    expect(html({})).toMatch(/<button[^>]*aria-label="Groceries: see transactions"/)
  })

  it('everything else, with Set a budget', () => {
    const t = text(html({}))
    expect(t).toContain('Everything else £392 no budget')
    expect(t).toContain('Set a budget')
  })

  it('the reconciliation line shows the arithmetic and says nothing changes', () => {
    const t = text(html({}))
    expect(t).toContain('Safe to spend £480 − £268 left in your budgets − £160 other spending at your pace = £52 headroom')
    expect(t).toContain('Information only. Your safe to spend is unchanged.')
    expect(t).not.toMatch(/you can spend/i)
  })

  it('"Not counted here" is a collapsed disclosure button', () => {
    expect(html({})).toMatch(/<button[^>]*aria-expanded="false"[^>]*>Not counted here<\/button>/)
  })

  it('no payday: the 30-day note, and no reconciliation line', () => {
    const data = budgetsResponse({ cycle: { ...budgetsResponse().cycle, fallback: true } })
    const t = text(html({ data }))
    expect(t).toContain(
      'Budgets follow your pay cycle. Set your payday on Commitments to line them up; until then this uses the last 30 days.',
    )
    expect(t).toContain("Budgets can't be compared to safe to spend until a payday is set.")
    expect(t).not.toContain('headroom')
  })

  it('stale accounts: the existing note', () => {
    const staleAccounts = [{ name: 'Monzo', last_synced_at: '2026-10-09T08:00:00Z' }]
    expect(text(html({ staleAccounts }))).toContain("Budgets may be behind: Monzo hasn't synced since 9 Oct.")
  })

  it('a category is text, never markup (BM13)', () => {
    const data = budgetsResponse({ budgets: [budget({ category: '<img src=x onerror=alert(1)>' })] })
    const h = html({ data })
    expect(h).not.toContain('<img')
    expect(h).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })

  it('a budget Claude changed carries the marker linked to its change', () => {
    const data = budgetsResponse({ budgets: [budget({ changed_by_claude: { audit_id: 'a9', at: '2026-10-12T09:00:00Z' } })] })
    expect(html({ data })).toMatch(/href="\/changes#change-a9"/)
  })

  it('only slate-400 or lighter for small text', () => {
    expect(html({})).not.toMatch(/text-slate-(500|600|700)/)
  })

  it('without the budget projection yet, the line says it can\'t compare', () => {
    expect(text(html({ data: budgetsResponse({ reconciliation: null }) }))).toContain("Budgets can't be compared to safe to spend until a payday is set.")
  })

  it('all paused: not the setup card; says they are paused and shows Everything else', () => {
    const data = budgetsResponse({ budgets: [budget({ paused: true, status: null })], reconciliation: null })
    const t = text(html({ data }))
    expect(t).not.toContain('Set a limit for the things you want to keep an eye on.')
    expect(t).toContain('All your budgets are paused. Their spending counts under Everything else.')
    expect(t).toContain('Everything else £392 no budget')
  })

  it('each bar has its own category colour, in list order', () => {
    const fills = [...html({}).matchAll(/data-fill[^>]*style="width:[^;]*;background-color:(#[0-9A-Fa-f]{6})"/g)].map((m) => m[1])
    expect(fills).toEqual(['#2DD4A7', '#38BDF8', '#A78BFA'])
  })

  it('the Budgets heading can take focus (BM18: after the first save)', () => {
    expect(html({})).toMatch(/<h2[^>]*id="budgets-heading"[^>]*tabindex="-1"/)
  })

  it('Manage budgets opens the sheet from the list header (T-09-7)', () => {
    expect(html({ onManage: noop })).toMatch(/<button[^>]*>Manage budgets<\/button>/)
    expect(html({})).not.toContain('Manage budgets')
  })

  it('a paused budget leaves the tracking list (its spending is in Everything else)', () => {
    const data = budgetsResponse({ budgets: [budget(), budget({ id: 'p', category: 'Hobbies', paused: true, status: null })] })
    expect(text(html({ data }))).not.toContain('Hobbies')
  })
})
