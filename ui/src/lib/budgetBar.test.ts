import { describe, expect, it } from 'vitest'
import { barGeometry, comingUpA11y, comingUpLine, overByPaydayText, takesYouOverLine } from './budgetBar'
import { budget } from './budgets.fixtures'
import type { Budget, ComingUpItem } from './budgets'

// T-24-5, spec nilu-s24-plan.md "Budget bar": the worked figures. Synthetic names.
const kit = (due: string, amount = '64.00'): ComingUpItem => ({ commitment_id: 'c-kit', label: 'Meal kit', due_date: due, amount })

function bar(spent: string, coming: ComingUpItem[], over: Partial<Budget> = {}): Budget {
  const amount = coming.reduce((t, i) => t + Number(i.amount), 0)
  const opb = Math.max(0, Number(spent) + amount - 500)
  return budget({
    category: 'Eating out', limit_pounds: 500, spent, pace_spent: '150.00',
    over_by: Math.max(0, Number(spent) - 500).toFixed(2),
    status: Number(spent) > 500 ? 'over' : Number(spent) === 500 ? 'budget_used' : 'ahead_of_pace',
    coming_up: {
      amount: amount.toFixed(2), commitment_count: new Set(coming.map((i) => i.commitment_id)).size,
      instalment_count: coming.length, items: coming,
    },
    over_by_payday: opb.toFixed(2),
    ...over,
  })
}
const three = [kit('2026-11-18'), kit('2026-11-25'), kit('2026-12-02')]
const two = [kit('2026-11-18'), kit('2026-11-25')]

describe('budget bar geometry (widths only; every figure is the API\'s)', () => {
  it('A1: within the limit, the scale is the limit and there is no marker', () => {
    const g = barGeometry(bar('92.00', three))
    expect(g.fill).toBeCloseTo(18.4, 1)
    expect(g.segmentStart).toBeCloseTo(18.4, 1)
    expect(g.segment).toBeCloseTo(38.4, 1)
    expect(g.marker).toBeNull()
    expect(g.pace).toBeCloseTo(30, 1)
  })

  it('A2: going over stretches the scale to spent + coming up, with the limit as a marker', () => {
    const g = barGeometry(bar('394.00', three))
    expect(g.fill).toBeCloseTo(67.2, 1)
    expect(g.segment).toBeCloseTo(32.8, 1)
    expect(g.marker).toBeCloseTo(85.3, 1)
    expect(g.pace).toBeCloseTo(25.6, 1) // the pace tick rescales with the bar
  })

  it('A3: over with more to come', () => {
    const g = barGeometry(bar('521.70', two))
    expect(g.fill).toBeCloseTo(80.3, 1)
    expect(g.segment).toBeCloseTo(19.7, 1)
    expect(g.marker).toBeCloseTo(77.0, 1)
  })

  it('A7: budget used with more to come', () => {
    expect(barGeometry(bar('500.00', two)).marker).toBeCloseTo(79.6, 1)
  })

  it('A4 and budget used with nothing to come: no segment, no marker, as today', () => {
    for (const spent of ['649.70', '500.00']) {
      const g = barGeometry(bar(spent, []))
      expect(g.fill).toBe(100)
      expect(g.segment).toBe(0)
      expect(g.marker).toBeNull()
    }
  })

  it('a budget with no coming_up field (older response) renders as before', () => {
    const g = barGeometry(budget())
    expect(g.fill).toBeCloseTo(70.67, 1)
    expect(g.segment).toBe(0)
    expect(g.marker).toBeNull()
  })
})

describe('budget bar words', () => {
  it('the coming-up line names one commitment and counts its instalments', () => {
    expect(comingUpLine(bar('92.00', three))).toBe('£192.00 coming up: Meal kit, 3 more this cycle')
    expect(comingUpLine(bar('92.00', []))).toBeNull()
  })

  it('two or more commitments: the largest is named, "and N other(s)", no count', () => {
    const items = [
      { commitment_id: 'c-small', label: 'Cloud notes', due_date: '2026-11-15', amount: '5.00' },
      { commitment_id: 'c-prime', label: 'Streamly', due_date: '2026-11-20', amount: '8.99' },
    ]
    expect(comingUpLine(bar('20.00', items))).toBe('£13.99 coming up: Streamly and 1 other')
    const tie = [
      { commitment_id: 'c-a', label: 'Later', due_date: '2026-11-22', amount: '8.99' },
      { commitment_id: 'c-b', label: 'Earlier', due_date: '2026-11-16', amount: '8.99' },
      { commitment_id: 'c-c', label: 'Small', due_date: '2026-11-17', amount: '1.00' },
    ]
    expect(comingUpLine(bar('20.00', tie))).toBe('£18.98 coming up: Earlier and 2 others')
  })

  it('"over by payday" comes from the API figure, only when there is one', () => {
    expect(overByPaydayText(bar('394.00', three))).toBe('£86.00 over by payday')
    expect(overByPaydayText(bar('521.70', two))).toBe('£149.70 over by payday')
    expect(overByPaydayText(bar('92.00', three))).toBeNull()
    expect(overByPaydayText(bar('394.00', three, { over_by_payday: '1.00' }))).toBe('£1.00 over by payday')
  })

  it('"will take you £C over" only once spent is at or over the limit', () => {
    expect(takesYouOverLine(bar('521.70', two))).toBe('Meal kit will take you £128.00 over')
    expect(takesYouOverLine(bar('500.00', two))).toBe('Meal kit will take you £128.00 over')
    expect(takesYouOverLine(bar('394.00', three))).toBeNull() // A2: the foot already says it
    expect(takesYouOverLine(bar('649.70', []))).toBeNull()
  })

  it('the meter\'s accessible name carries coming up and over by payday in words', () => {
    expect(comingUpA11y(bar('521.70', two))).toBe(
      '£128.00 coming up from Meal kit, 2 more this cycle, not counted as spent, £149.70 over by payday if all are paid')
    expect(comingUpA11y(bar('92.00', three))).toBe('£192.00 coming up from Meal kit, 3 more this cycle, not counted as spent')
    expect(comingUpA11y(bar('92.00', []))).toBeNull()
  })
})
