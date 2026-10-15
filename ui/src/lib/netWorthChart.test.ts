import { describe, expect, it } from 'vitest'
import { forecastRows, parseView, yearTicks } from './netWorthChart'

// The Wealth graph's History / Forecast views (owner 2026-10-15): with a
// target the projection gets its own view on a real date axis, so history
// and its line switches keep the full width in the History view.
const history = [
  { date: '2026-08-31', net_worth: '-6000.00' },
  { date: '2026-09-30', net_worth: '-5900.00' },
  { date: '2026-10-15', net_worth: '-5938.00' },
]
const timeline = [
  { date: '2026-10-15', value: '-5938.00' },
  { date: '2026-11-15', value: '-4900.00' },
  { date: '2026-12-15', value: '-3800.00' },
]
const t = (d: string) => new Date(d).getTime()

describe('parseView', () => {
  it('is History when there is no forecast, whatever was stored', () => {
    expect(parseView('forecast', false)).toBe('history')
    expect(parseView(null, false)).toBe('history')
  })
  it('opens on Forecast when a forecast exists, unless History was chosen', () => {
    expect(parseView(null, true)).toBe('forecast')
    expect(parseView('junk', true)).toBe('forecast')
    expect(parseView('history', true)).toBe('history')
  })
})

describe('forecastRows', () => {
  it('places every point at its own date, history then projection, joined at today', () => {
    const rows = forecastRows(history, timeline)
    expect(rows.map((r) => r.t)).toEqual([
      t('2026-08-31'), t('2026-09-30'), t('2026-10-15'), t('2026-11-15'), t('2026-12-15'),
    ])
    // Today carries both keys so the solid and dashed lines meet.
    expect(rows[2]).toEqual({ t: t('2026-10-15'), 'Net worth': -5938, Projected: -5938 })
    expect(rows[1]).toEqual({ t: t('2026-09-30'), 'Net worth': -5900 })
    expect(rows[4]).toEqual({ t: t('2026-12-15'), Projected: -3800 })
  })
  it('is empty without history or a projection', () => {
    expect(forecastRows([], timeline)).toEqual([])
    expect(forecastRows(history, [])).toEqual([])
  })
})

describe('yearTicks', () => {
  it('gives a few evenly spaced 1 January ticks inside the range', () => {
    const ticks = yearTicks(t('2026-08-31'), t('2050-02-15'))
    expect(ticks.map((v) => new Date(v).getUTCFullYear())).toEqual([2027, 2035, 2043])
    ticks.forEach((v) => expect(new Date(v).toISOString().slice(5, 10)).toBe('01-01'))
  })
  it('steps one year at a time over a short range', () => {
    const ticks = yearTicks(t('2026-08-31'), t('2029-06-15'))
    expect(ticks.map((v) => new Date(v).getUTCFullYear())).toEqual([2027, 2028, 2029])
  })
  it('falls back to the two ends when the range has no 1 January', () => {
    expect(yearTicks(t('2026-08-31'), t('2026-12-15'))).toEqual([t('2026-08-31'), t('2026-12-15')])
  })
})
