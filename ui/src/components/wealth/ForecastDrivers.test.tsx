import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ForecastDrivers from './ForecastDrivers'

const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

describe('ForecastDrivers', () => {
  const drivers = {
    rows: [
      { label: 'Income', detail: 'your income commitments', amount: 3200 },
      { label: 'Everyday spending', detail: 'your budgets', amount: -1450 },
    ],
    total: 1750, growthPct: 5, notes: ['Everyday spending is not subtracted.'],
  }

  it('lists each driver with its sign, then the monthly total and the growth on top', () => {
    const t = text(renderToStaticMarkup(<ForecastDrivers drivers={drivers} />))
    expect(t).toMatch(/What moves it each month .*Income .*your income commitments .*\+£3,200 .*Everyday spending .*your budgets .*−£1,450/)
    expect(t).toMatch(/Net worth change before growth .*\+£1,750 a month/)
    expect(t).toContain('Plus 5% a year growth on what is invested.')
    expect(t).toContain('Everyday spending is not subtracted.')
  })

  it('is a labelled list', () => {
    const h = renderToStaticMarkup(<ForecastDrivers drivers={drivers} />)
    expect(h).toMatch(/<section[^>]*aria-labelledby="forecast-drivers-heading"/)
    expect((h.match(/<li/g) ?? []).length).toBe(2)
    expect(h).not.toContain('text-slate-500')
  })
})
