import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import PlannedItems from './PlannedItems'
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
