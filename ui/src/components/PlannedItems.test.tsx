import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import PlannedItems, { AddPlannedModal } from './PlannedItems'
import type { PlannedItem } from '../types'

const item = (over: Partial<PlannedItem> = {}): PlannedItem => ({
  id: 'p1', name: 'Dentist', direction: 'expense', kind: 'one_off', start_date: '2026-10-14', amount: 50,
  total_amount: null, installments: null, cadence: null, interval_days: null, interval_months: null,
  end_date: null, apr: null, fee_amount: null, active: true, ...over,
})
const render = (items: PlannedItem[]) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <PlannedItems items={items} onChanged={() => {}} />
    </MemoryRouter>,
  )

describe('PlannedItems markers (M1, M4)', () => {
  it("shows the Changed by Claude link only on an item Claude changed", () => {
    const h = render([item({ changed_by_claude: { audit_id: 'a7', at: '2026-10-09T10:00:00Z' } }), item({ id: 'p2', name: 'Mine' })])
    expect(h.match(/href="\/changes#change-/g)).toHaveLength(1)
    expect(h).toContain('href="/changes#change-a7"')
  })

  it('planned income says it is not counted until it arrives; an expense does not', () => {
    expect(render([item({ direction: 'income', name: 'Refund' })])).toContain(
      'Not counted in your safe to spend until it arrives.',
    )
    expect(render([item()])).not.toContain('Not counted in your safe to spend')
  })
})

describe('PlannedItems Paid (P1-P3, P5, P6)', () => {
  it('P1/P3: a matched item, income or expense, shows Paid and a muted amount', () => {
    for (const direction of ['income', 'expense']) {
      const h = render([item({ direction, matched_transaction_id: 't9' })])
      expect(h).toMatch(/class="chip-pos[^"]*"[^>]*>Paid</)
      expect(h).toMatch(/<div class="text-sm tnum text-slate-400"/)
    }
  })

  it('P2: no match, no Paid', () => {
    expect(render([item({ matched_transaction_id: null })])).not.toContain('>Paid<')
    expect(render([item()])).not.toContain('>Paid<')
  })

  it('P5/P6: no transaction detail or link; Remove stays', () => {
    const h = render([item({ matched_transaction_id: 't9-secret-id' })])
    expect(h).not.toContain('t9-secret-id')
    expect(h).not.toMatch(/<a[^>]*>[^<]*Paid/)
    expect(h).toContain('>Remove</button>')
  })
})

describe('PlannedItems card payment (T-12-7a, ux O-1, O-2, O-4, X-1, X-2)', () => {
  const flagged = (over: Partial<PlannedItem> = {}) =>
    item({ name: 'Card bill', amount: 400, is_card_payment: true, card_payment_overlap: true, ...over })

  it('O-2: a ticked item in a window with projected card bills shows the chip and says Card payment', () => {
    const h = render([flagged()])
    expect(h).toMatch(/class="chip-warn[^"]*"[^>]*>Overlaps card bills</)
    expect(h).toContain('Card payment · £400.00 · ')
  })

  it('no overlap, no chip; unticked (O-4), neither the chip nor the words', () => {
    expect(render([flagged({ card_payment_overlap: false })])).not.toContain('Overlaps card bills')
    const h = render([item({ name: 'Amex bill', is_card_payment: false, card_payment_overlap: false })])
    expect(h).not.toContain('Overlaps card bills')
    expect(h).not.toContain('Card payment ·')
  })

  it('an existing expense can be ticked or unticked on its row (a native checkbox); income cannot', () => {
    const h = render([flagged(), item({ id: 'p2', name: 'Refund', direction: 'income' })])
    expect(h.match(/type="checkbox"/g)).toHaveLength(1)
    expect(h).toMatch(/<input[^>]*type="checkbox"[^>]*checked=""/)
    expect(h).toContain('aria-label="Card payment: Card bill"')
  })

  it('X-1/X-2: the add form has a labelled Card payment checkbox with its help, and no card select', () => {
    const h = renderToStaticMarkup(<AddPlannedModal onClose={() => {}} onAdded={() => {}} />)
    expect(h).toMatch(/<input[^>]*id="planned-card-payment"[^>]*type="checkbox"[^>]*aria-describedby="planned-card-payment-help"/)
    expect(h).toContain('<label for="planned-card-payment"')
    expect(h).toContain('Tick this if it pays a credit card, so nilu counts it once with your projected card bills.')
    expect(h).not.toMatch(/<select[^>]*card/i)
  })
})
