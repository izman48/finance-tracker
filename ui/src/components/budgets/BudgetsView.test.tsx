import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import BudgetsView, { type BudgetsViewProps } from './BudgetsView'
import { budget, budgetsResponse, summaryThisCycle } from '../../lib/budgets.fixtures'

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
    expect(t).toContain('Measuring purchases and commitments you have paid. Not counted here: commitments with no budget, transfers, card payoffs.')
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

  it('BX1: the Your budgets box, exactly, in place of the old reconciliation', () => {
    const t = text(html({}))
    expect(t).toContain('Your budgets')
    expect(t).toContain('£890 this cycle. Spent £631, £259 left.')
    expect(t).toContain('Bills are already in your safe to spend. Budgets are for your day-to-day spending.')
    expect(t).not.toContain('How this fits with safe to spend')
  })

  it('BX2/BX3: over appended without red; paused counted out', () => {
    const data = budgetsResponse({ summary_this_cycle: summaryThisCycle({ first_over: { category: 'Eating out', over_by: '12' }, paused_count: 2 }) })
    const h = html({ data })
    expect(text(h)).toContain('£890 this cycle. Spent £631, £259 left. Eating out is £12 over.')
    expect(text(h)).toContain("2 paused budgets aren't counted.")
    // ux on #169: the paused line comes after the bills line
    expect(text(h).indexOf("2 paused budgets aren't counted.")).toBeGreaterThan(text(h).indexOf('Budgets are for your day-to-day spending.'))
    expect(h.slice(h.indexOf('id="budgets-box"'))).not.toMatch(/text-neg|text-warn/)
  })

  it('BX6: the box has no headroom, safe-to-spend amount or arithmetic', () => {
    const h = html({})
    const box = text(h.slice(h.indexOf('id="budgets-box"'), h.indexOf('Not counted here')))
    expect(box).not.toMatch(/headroom|[−=]|at your pace/)
  })

  it('"Not counted here" is a collapsed disclosure button', () => {
    expect(html({})).toMatch(/<button[^>]*aria-expanded="false"[^>]*>Not counted here<\/button>/)
  })

  it('no payday: the 30-day note, and the box still shows', () => {
    const data = budgetsResponse({ cycle: { ...budgetsResponse().cycle, fallback: true } })
    const t = text(html({ data }))
    expect(t).toContain(
      'Budgets follow your pay cycle. Set your payday on Commitments to line them up; until then this uses the last 30 days.',
    )
    expect(t).toContain('£890 this cycle. Spent £631, £259 left.')
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

  it('all paused: not the setup card; says they are paused and shows Everything else', () => {
    const data = budgetsResponse({
      budgets: [budget({ paused: true, status: null })],
      summary_this_cycle: summaryThisCycle({ total_limit: '0', spent: '0', left: '0', paused_count: 1 }),
    })
    const t = text(html({ data }))
    expect(t).toContain('All your budgets are paused, so none are counted.') // BX4
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

  // --- commitments coming up (T-24-5; spec "Budget bar", frames A1-A7) -------------
  const kit = (due: string) => ({ commitment_id: 'c-kit', label: 'Meal kit', due_date: due, amount: '64.00' })
  const eating = (spent: string, items: ReturnType<typeof kit>[], opb: string) => budget({
    id: 'e', category: 'Eating out', limit_pounds: 500, spent, pace_spent: '150.00',
    over_by: Math.max(0, Number(spent) - 500).toFixed(2),
    status: Number(spent) > 500 ? 'over' : Number(spent) === 500 ? 'budget_used' : 'ahead_of_pace',
    coming_up: { amount: (64 * items.length).toFixed(2), commitment_count: items.length ? 1 : 0, instalment_count: items.length, items },
    over_by_payday: opb,
  })
  const row = (b: ReturnType<typeof budget>) => html({ data: budgetsResponse({ budgets: [b] }) })
  const three = [kit('2026-11-18'), kit('2026-11-25'), kit('2026-12-02')]
  const two = [kit('2026-11-18'), kit('2026-11-25')]

  it('A1: a hatched coming-up segment after the fill, its line, no marker, no "over by payday"', () => {
    const h = row(eating('92.00', three, '0.00'))
    expect(h).toMatch(/data-coming[^>]*aria-hidden="true"[^>]*style="left:18\.4\d*%;width:38\.4\d*%/)
    expect(h).not.toContain('data-limit')
    expect(text(h)).toContain('£192.00 coming up: Meal kit, 3 more this cycle')
    expect(text(h)).toContain('Ahead of pace')
    expect(text(h)).not.toContain('over by payday')
  })

  it('A2: going over stretches the bar, marks the limit with its label, and says over by payday', () => {
    const h = row(eating('394.00', three, '86.00'))
    expect(h).toMatch(/data-limit[^>]*style="left:85\.3\d*%/)
    expect(text(h)).toMatch(/£500 .*Ahead of pace · £86\.00 over by payday/)
    expect(text(h)).not.toContain('will take you')
  })

  it('A3: over with more to come: "£21.70 over · £149.70 over by payday" and the take-you-over line, no end cap', () => {
    const h = row(eating('521.70', two, '149.70'))
    expect(h).toMatch(/<span class="chip-out">£21\.70 over<\/span>/)
    expect(text(h)).toContain('£21.70 over · £149.70 over by payday')
    expect(text(h)).toContain('Meal kit will take you £128.00 over')
    expect(h).not.toContain('data-endcap')
    expect(h).not.toMatch(/text-neg|bg-neg|text-rose|bg-rose/)
  })

  it('A7: budget used, with more to come', () => {
    const h = row(eating('500.00', two, '128.00'))
    expect(h).toMatch(/<span class="chip">Budget used<\/span>/)
    expect(text(h)).toContain('Budget used · £128.00 over by payday')
    expect(text(h)).toContain('Meal kit will take you £128.00 over')
    expect(text(h)).not.toMatch(/On pace|Ahead of pace|Under pace/)
  })

  it('A4: over with nothing to come renders as today (end cap, no marker, no segment)', () => {
    const h = row(eating('649.70', [], '149.70'))
    expect(h).toContain('data-endcap')
    expect(h).not.toContain('data-limit')
    expect(h).not.toContain('data-coming')
  })

  it("the meter's name says what is coming up and that it isn't spent yet", () => {
    expect(row(eating('521.70', two, '149.70'))).toContain(
      'aria-label="Eating out: £521.70 of £500, £21.70 over, 18 days left, £128.00 coming up from Meal kit, 2 more this cycle, not counted as spent, £149.70 over by payday if all are paid"')
  })

  it('the coming-up line is a button that opens each instalment with its date and amount', () => {
    const h = row(eating('92.00', three, '0.00'))
    const [, id] = h.match(/<button[^>]*aria-expanded="false"[^>]*aria-controls="([^"]+)"[^>]*>.*?£192\.00 coming up/) ?? []
    expect(id).toBeTruthy()
    expect(h).toMatch(new RegExp(`id="${id}"[^>]*hidden`))
    expect(text(h)).toContain('Meal kit 18 Nov £64.00')
  })

  it('a coming-up label is text, never markup', () => {
    const b = eating('92.00', [{ ...kit('2026-11-18'), label: '<img src=x onerror=alert(1)>' }], '0.00')
    const h = row(b)
    expect(h).not.toContain('<img')
    expect(h).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })

  it('Not counted here: commitments with no budget link to Plan; no category only when there is some', () => {
    const t = text(html({}))
    expect(t).toContain('Commitments with no budget See in Plan £1,203')
    expect(t).not.toContain('Commitments with no category')
    expect(html({})).toMatch(/<a[^>]*href="\/dashboard#plan"[^>]*>See in Plan<\/a>/)
    const data = budgetsResponse({ not_counted: { ...budgetsResponse().not_counted, commitments_no_category: '12.50' } })
    expect(text(html({ data }))).toContain('Commitments with no category £12.50')
  })
})
