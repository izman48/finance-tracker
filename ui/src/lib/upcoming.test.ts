import { describe, expect, it } from 'vitest'
import { buildUpcoming } from './upcoming'
import type { Commitment, PlannedItem } from '../types'

const today = '2026-10-10'

const commitment = (over: Partial<Commitment> = {}): Commitment => ({
  id: 'c1', direction: 'expense', label: 'Gym', amount: 30, cadence: 'monthly', interval_days: null,
  interval_months: null, next_date: '2026-10-12', source: 'manual', status: 'confirmed', account_id: null,
  match_key: null, ...over,
})

const planned = (over: Partial<PlannedItem> = {}): PlannedItem => ({
  id: 'p1', name: 'Dentist', direction: 'expense', kind: 'one_off', start_date: '2026-10-14', amount: 50,
  total_amount: null, installments: null, cadence: null, interval_days: null, interval_months: null,
  end_date: null, apr: null, fee_amount: null, active: true, ...over,
})

describe('buildUpcoming', () => {
  it('drops a planned item its real transaction already paid (T-08-7)', () => {
    const rows = buildUpcoming([], [], [planned(), planned({ id: 'p2', name: 'Paid early', matched_transaction_id: 't9' })], today)
    expect(rows.map((r) => r.label)).toEqual(['Dentist'])
  })

  it("carries Claude's latest change so the row can link to it (M1)", () => {
    const rows = buildUpcoming(
      [commitment({ changed_by_claude: { audit_id: 'a1', at: '2026-10-09T10:00:00Z' } })],
      [],
      [planned({ changed_by_claude: { audit_id: 'a2', at: '2026-10-09T10:00:00Z' } }), planned({ id: 'p3', name: 'Mine' })],
      today,
    )
    expect(rows.map((r) => [r.label, r.claudeAuditId])).toEqual([
      ['Gym', 'a1'],
      ['Dentist', 'a2'],
      ['Mine', undefined],
    ])
  })

  it('flags planned income, which is shown but not counted (D1)', () => {
    const rows = buildUpcoming([], [], [planned({ direction: 'income', name: 'Refund' })], today)
    expect(rows[0]).toMatchObject({ income: true, plannedIncome: true })
    expect(buildUpcoming([commitment({ direction: 'income' })], [], [], today)[0].plannedIncome).toBeFalsy()
  })
})
