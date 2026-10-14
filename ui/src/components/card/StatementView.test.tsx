import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import StatementView, { type StatementViewProps } from './StatementView'
import type { CardStatements } from '../../services/api'

// Card settings, Statement block (ux T-10-0 A.2/A.4, criteria C-1..C-3,
// C-10..C-12, C-19..C-21). Synthetic fixture: statement £5,000.00, current
// £6,000.00, unbilled £1,000.00, paid from Test Current.
const noop = () => {}
const manual = { id: 'm1', account_id: 'c1', statement_balance: '5000.00', statement_date: '2026-09-30', due_date: '2026-10-31', minimum_due: null, source: 'manual' as const }
const data = (over: Partial<CardStatements> = {}, current: Record<string, unknown> = {}): CardStatements => ({
  statements: [manual],
  current: {
    statement_id: 'm1', source: 'manual', statement_balance: '5000.00', statement_date: '2026-09-30', due_date: '2026-10-31',
    minimum_due: null, payments_since_statement: '0', amount_still_due: '5000.00', unbilled: '1000.00', paid: false, ...current,
  } as CardStatements['current'],
  missing_statement: false,
  conflict: false,
  next_payment: { amount: '5000.00', date: '2026-10-31', from_account_name: 'Test Current' },
  ...over,
})
const html = (props: Partial<StatementViewProps>) =>
  renderToStaticMarkup(
    <StatementView status="ready" data={data()} currentBalance="6000.00" providerName="Test Bank"
      onRetry={noop} onAdd={noop} onEdit={noop} onChoose={noop} onUse={noop} {...props} />,
  )
const text = (h: string) =>
  h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('StatementView', () => {
  it('C-1: rows from the API, with the "Entered by you" chip', () => {
    const t = text(html({}))
    for (const part of ['Statement balance £5,000.00', 'Statement date 30 Sept 2026', 'Due date 31 Oct 2026',
      'Still to pay £5,000.00', 'Spent since the statement £1,000.00', 'Entered by you', 'Edit statement']) {
      expect(t).toContain(part.replace('Sept', new Date('2026-09-30').toLocaleDateString('en-GB', { month: 'short' })))
    }
    expect(t).not.toContain('Minimum payment')
  })

  it('C-2: the sentence from next_payment, and none without it', () => {
    expect(text(html({}))).toContain(
      'nilu will pay £5,000.00 on 31 Oct 2026 from Test Current. The £1,000.00 spent since goes on your next bill.')
    expect(text(html({ data: data({ next_payment: null }) }))).not.toContain('nilu will pay')
  })

  it('C-3: no statement: the current balance and Add statement', () => {
    const t = text(html({ data: data({ statements: [], current: null, next_payment: null }) }))
    expect(t).toContain('No statement entered yet. Until you add one, nilu plans to pay your full current balance of £6,000.00 on the card\'s next payment date.')
    expect(html({ data: data({ statements: [], current: null }) })).toMatch(/<button[^>]*>Add statement<\/button>/)
  })

  it('T-10-12: no statement and no repayment set up: no claim about a payment', () => {
    const t = text(html({ data: data({ statements: [], current: null, next_payment: null }), notInForecast: true }))
    expect(t).toContain('No statement entered yet.')
    expect(t).not.toContain('nilu plans to pay')
  })

  it('C-10: paid shows the Paid chip and the paid sentence', () => {
    const h = html({ data: data({}, { amount_still_due: '0.00', paid: true }) })
    expect(h).toMatch(/class="chip-pos">Paid</)
    expect(text(h)).toContain('This statement is paid. The £1,000.00 spent since goes on your next bill.')
  })

  it('C-11: a conflict shows both, the in-use one checked, Use this statement disabled until changed', () => {
    const provider = { ...manual, id: 'p1', statement_balance: '4990.00', source: 'provider' as const }
    const conflict = data({ statements: [manual, provider], conflict: true })
    const h = html({ data: conflict })
    const t = text(h)
    expect(t).toContain("Your figures and Test Bank's figures for this statement are different.")
    expect(t).toContain('Entered by you')
    expect(t).toContain('From Test Bank')
    expect(t).toContain('£4,990.00 · statement')
    const radio = (id: string) => h.match(new RegExp(`<input[^>]*value="${id}"[^>]*>`))![0]
    expect(radio('m1')).toContain('checked=""')
    expect(radio('p1')).not.toContain('checked=""')
    expect(h).toMatch(/<button[^>]*disabled=""[^>]*>Use this statement<\/button>/)
    expect(html({ data: conflict, choice: 'p1' })).not.toMatch(/<button[^>]*disabled=""[^>]*>Use this statement/)
    expect(text(html({}))).not.toContain('Which statement is right?')
  })

  it('C-12: the missing-statement banner only when the due date has passed', () => {
    const t = text(html({ data: data({ missing_statement: true }) }))
    expect(t).toContain('Your statement due 31 Oct 2026 has passed. Add your new statement so nilu plans the right bill. Until then it plans your full current balance of £6,000.00.')
    expect(t).toContain('Add new statement')
    expect(t).toContain('Past due date')
    expect(text(html({}))).not.toContain('has passed')
  })

  it('C-19: a provider name with markup is shown as text', () => {
    const h = html({ data: data({}, { source: 'provider' }), providerName: '<b>x</b>' })
    expect(h).not.toContain('<b>x</b>')
    expect(h).toContain('From &lt;b&gt;x&lt;/b&gt;')
  })

  it('C-20: an unsaved switch to credit asks to save first', () => {
    expect(text(html({ status: 'unsaved', data: null }))).toContain('Save this account as a credit card first, then you can add a statement.')
  })

  it('C-21 and errors: not found, load error with Try again, loading', () => {
    expect(text(html({ status: 'notfound', data: null }))).toContain('We could not find this card. Close this window and reload the page.')
    const err = html({ status: 'error', data: null })
    expect(text(err)).toContain("We could not load this card's statement. Your repayment settings below are unchanged.")
    expect(err).toMatch(/<button[^>]*>Try again<\/button>/)
    expect(html({ status: 'loading', data: null })).toMatch(/role="status"[^>]*>Loading statement…/)
  })

  it('read-only: no write buttons without their actions, and a conflict lists both values without radios', () => {
    const provider = { ...manual, id: 'p1', statement_balance: '4990.00', source: 'provider' as const }
    const readOnly = renderToStaticMarkup(
      <StatementView status="ready" data={data({ statements: [manual, provider], conflict: true, missing_statement: true })}
        currentBalance="6000.00" providerName="Test Bank" onRetry={noop} />,
    )
    expect(readOnly).not.toMatch(/<button[^>]*>(Edit statement|Add new statement|Use this statement)<\/button>/)
    expect(readOnly).not.toContain('type="radio"')
    expect(text(readOnly)).toContain('From Test Bank £4,990.00 · statement')
  })

  it('ux on #182: read-only conflict banner gives no instruction it cannot act on', () => {
    const provider = { ...manual, id: 'p1', statement_balance: '4990.00', source: 'provider' as const }
    const readOnly = renderToStaticMarkup(
      <StatementView status="ready" data={data({ statements: [manual, provider], conflict: true })}
        currentBalance="6000.00" providerName="Test Bank" onRetry={noop} />,
    )
    expect(text(readOnly)).toContain("Your figures and Test Bank's figures for this statement are different.")
    expect(text(readOnly)).not.toContain('Pick the one')
  })

  it('ux on #182: aria-busy while loading, and the heading is not the muted label style', () => {
    expect(html({ status: 'loading', data: null })).toMatch(/<section[^>]*aria-busy="true"/)
    expect(html({})).not.toMatch(/<section[^>]*aria-busy="true"/)
    expect(html({})).toMatch(/<h4 id="statement-heading" class="text-sm font-semibold text-slate-100"/)
  })

  it('ux on #182: a card that owes nothing never reads "full current balance of -£x"', () => {
    for (const balance of ['0', '-25.00']) {
      const empty = text(html({ data: data({ statements: [], current: null, next_payment: null }), currentBalance: balance }))
      expect(empty).toContain('No statement entered yet. nilu has no balance to plan for this card yet.')
      expect(empty).not.toContain('full current balance')
      const missing = text(html({ data: data({ missing_statement: true }), currentBalance: balance }))
      expect(missing).not.toContain('full current balance')
    }
  })

  it('a2: an open form replaces the rows, a failed pick says nothing changed, Edit has an id for focus', () => {
    const withForm = text(html({ form: <p>FORM HERE</p> }))
    expect(withForm).toContain('FORM HERE')
    expect(withForm).not.toContain('Statement balance £5,000.00')
    const provider = { ...manual, id: 'p1', statement_balance: '4990.00', source: 'provider' as const }
    expect(text(html({ data: data({ statements: [manual, provider], conflict: true }), useError: true }))).toContain(
      'We could not change which statement is used. Nothing was changed. Try again.')
    expect(html({})).toMatch(/<button[^>]*id="statement-edit"[^>]*>Edit statement<\/button>/)
  })

  it('ux on #184: Add and Use this statement have ids to return focus to', () => {
    expect(html({ data: data({ statements: [], current: null }) })).toMatch(/<button[^>]*id="statement-add"[^>]*>Add statement</)
    expect(html({ data: data({ missing_statement: true }) })).toMatch(/<button[^>]*id="statement-add"[^>]*>Add new statement</)
    const provider = { ...manual, id: 'p1', statement_balance: '4990.00', source: 'provider' as const }
    expect(html({ data: data({ statements: [manual, provider], conflict: true }) })).toMatch(/<button[^>]*id="statement-use"/)
  })
})
