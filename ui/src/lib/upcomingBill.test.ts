import { describe, expect, it } from 'vitest'
import { buildUpcoming } from './upcoming'
import { homeUpcomingLabel } from './homeOwed'

// T-12-7a: a card repayment reads "{card} bill" or "{card} bill (projected)"
// on Cashflow and Home alike, and carries the API's parts.
describe('card bills in Coming up', () => {
  const rows = buildUpcoming([], [
    { account_id: 'c1', label: 'Amex Gold', amount: 500, due_date: '2026-10-31', projected: false, parts: [{ kind: 'statement', amount: 500 }] },
    { account_id: 'c1', label: 'Amex Gold', amount: 140, due_date: '2026-11-30', projected: true, parts: [{ kind: 'spent_since', amount: 140 }] },
    { account_id: 'c2', label: 'Old Card', amount: 90, due_date: '2026-11-01' },
  ], [], '2026-10-15')

  it('labels each bill once, the same on Home', () => {
    expect(rows.map((r) => r.label)).toEqual(['Amex Gold bill', 'Old Card bill', 'Amex Gold bill (projected)'])
    expect(rows.map((r) => homeUpcomingLabel(r))).toEqual(['Amex Gold bill', 'Old Card bill', 'Amex Gold bill (projected)'])
  })

  it("carries the API's parts", () => {
    expect(rows[2].billParts).toEqual([{ kind: 'spent_since', amount: 140 }])
    expect(rows[1].billParts).toBeUndefined()
  })
})
