import { describe, expect, it } from 'vitest'
import { buildUpcoming, upcomingAmount, upcomingShowsDate } from './upcoming'
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

describe('late income in coming-up (L1, L4)', () => {
  it('lists late income above every future row, most overdue first, with its expected date', () => {
    const rows = buildUpcoming(
      [
        commitment({ id: 'gym', label: 'Gym', next_date: '2026-10-11' }),
        commitment({ id: 'sal', label: 'Income A', direction: 'income', next_date: '2026-11-03', late: true, expected_date: '2026-10-03' }),
      ],
      [],
      [planned({ id: 'ref', name: 'Refund', direction: 'income', start_date: '2026-10-01', late: true })],
      today,
      10,
    )
    expect(rows.map((r) => [r.label, r.date, r.late?.days])).toEqual([
      ['Refund', '2026-10-01', 9],
      ['Income A', '2026-10-03', 7],
      ['Gym', '2026-10-11', undefined],
      ['Income A', '2026-11-03', undefined],
    ])
  })

  it('L1: a late row has no + and is not shown as money you have', () => {
    const [late] = buildUpcoming([commitment({ direction: 'income', late: true, expected_date: '2026-10-03' })], [], [], today)
    expect(upcomingAmount(late)).toEqual({ sign: '', tone: 'text-slate-400' })
    const [future] = buildUpcoming([commitment({ direction: 'income' })], [], [], today)
    expect(upcomingAmount(future)).toEqual({ sign: '+', tone: 'text-pos' })
    expect(upcomingAmount({ ...future, income: false })).toEqual({ sign: '', tone: 'text-slate-100' })
  })

  it('L4: once the API says it is no longer late, the row is gone', () => {
    const rows = buildUpcoming([commitment({ direction: 'income', late: false, expected_date: null, next_date: '2026-11-03' })], [], [], today)
    expect(rows.every((r) => !r.late)).toBe(true)
  })
})

describe('late rows show their date once (ux nit)', () => {
  it('a late row leaves the date to its "Expected" line', () => {
    const [late] = buildUpcoming([commitment({ direction: 'income', late: true, expected_date: '2026-10-03' })], [], [], today)
    expect(upcomingShowsDate(late)).toBe(false)
    const [future] = buildUpcoming([commitment()], [], [], today)
    expect(upcomingShowsDate(future)).toBe(true)
  })
})

describe('overdue planned expenses (O1-O5, P4)', () => {
  const overdue = (id: string, start: string) =>
    planned({ id, name: `Bill ${id}`, start_date: start, overdue: true })

  it('O3: overdue expenses join late income at the top, most overdue first', () => {
    const rows = buildUpcoming(
      [
        commitment({ id: 'g', label: 'Gym', next_date: '2026-10-11' }),
        commitment({ id: 's', label: 'Income A', direction: 'income', next_date: '2026-11-03', late: true, expected_date: '2026-10-03' }),
      ],
      [],
      [overdue('a', '2026-10-05'), overdue('b', '2026-10-01')],
      today,
      10,
    )
    expect(rows.slice(0, 3).map((r) => [r.label, r.late?.days ?? null, r.overdue?.days ?? null])).toEqual([
      ['Bill b', null, 9],
      ['Income A', 7, null],
      ['Bill a', null, 5],
    ])
    expect(rows[3].label).toBe('Gym')
  })

  it('O2: an overdue expense still reads as money going out', () => {
    const [row] = buildUpcoming([], [], [overdue('a', '2026-10-05')], today)
    expect(upcomingAmount(row)).toEqual({ sign: '', tone: 'text-slate-100' })
    expect(row.plannedIncome).toBeFalsy()
  })

  it('O4/O5: no overdue flag, income, or a matched item never shows Overdue', () => {
    const rows = buildUpcoming(
      [],
      [],
      [
        planned({ id: 'x', start_date: '2026-10-20', overdue: false }),
        planned({ id: 'i', direction: 'income', start_date: '2026-10-01', overdue: true, late: true }),
        planned({ id: 'm', start_date: '2026-10-05', overdue: true, matched_transaction_id: 't9' }),
      ],
      today,
      10,
    )
    expect(rows.filter((r) => r.overdue)).toEqual([])
    expect(rows.map((r) => r.key).some((k) => k.includes('-m'))).toBe(false)
  })
})
