import { describe, expect, it } from 'vitest'
import {
  answerSentence, contributionOf, graphStateNotes, inputsLine, investmentLine, isInvestment, investmentsTotal,
  LOOK_AHEAD, axisLabel, chartPoints, currentValue, wealthFormLink, graphDefaultGrowth, lastValueLine, parseValueToday, tablePoints, type InvestmentGraph,
} from './investments'
import type { Asset } from '../services/api'

// Wealth > Investments and the investment graph (T-11-5; ux T-11-2 "Words").
// Synthetic figures only.
const asset = (over: Partial<Asset> = {}): Asset => ({
  id: 'a1', name: 'Test ISA', asset_type: 'isa', assumed_growth_pct: '7.00', monthly_contribution: '1000.00',
  valuations: [{ id: 'v1', value: '18000.00', valued_at: '2026-10-01' }], ...over,
})

describe('which assets are investments (owner D1)', () => {
  it.each(['isa', 'investment', 'pension', 'crypto'])('%s is an investment', (t) => expect(isInvestment(t)).toBe(true))
  it.each(['savings', 'property', 'other', 'loan', 'mortgage'])('%s is not', (t) => expect(isInvestment(t)).toBe(false))
})

describe('the row line', () => {
  it('type, growth a year and contribution a month', () => {
    expect(investmentLine(asset())).toBe('ISA · 7% a year · £1,000 a month')
  })
  it('no contribution', () => {
    expect(investmentLine(asset({ asset_type: 'pension', assumed_growth_pct: '5', monthly_contribution: null })))
      .toBe('Pension · 5% a year · no monthly contribution')
    expect(investmentLine(asset({ monthly_contribution: '0.00' }))).toBe('ISA · 7% a year · no monthly contribution')
  })
  it('growth not set', () => {
    expect(investmentLine(asset({ assumed_growth_pct: null, monthly_contribution: null }))).toBe('ISA · growth not set')
  })
  it('a linked bill carries the contribution', () => {
    const linked = asset({ monthly_contribution: null, linked_commitment: { id: 'c1', label: 'Test ISA contribution', amount: '1000.00' } })
    expect(contributionOf(linked)).toBe(1000)
    expect(investmentLine(linked)).toBe('ISA · 7% a year · £1,000 a month')
  })
  it('keeps pence and a decimal rate', () => {
    expect(investmentLine(asset({ assumed_growth_pct: '6.50', monthly_contribution: '250.50' })))
      .toBe('ISA · 6.5% a year · £250.50 a month')
  })
  it('Investment and Crypto labels', () => {
    expect(investmentLine(asset({ asset_type: 'investment' }))).toMatch(/^Investment ·/)
    expect(investmentLine(asset({ asset_type: 'crypto' }))).toMatch(/^Crypto ·/)
  })
})

describe('the group total', () => {
  it('sums the latest value of investments only', () => {
    const list = [
      asset(),
      asset({ id: 'a2', asset_type: 'pension', valuations: [{ id: 'v', value: '10000.00', valued_at: '2026-09-01' }] }),
      asset({ id: 'a3', asset_type: 'property', valuations: [{ id: 'v', value: '250000.00', valued_at: '2026-09-01' }] }),
    ]
    expect(investmentsTotal(list)).toBe(28000)
  })
})

const graph = (over: Partial<InvestmentGraph> = {}): InvestmentGraph => ({
  as_of: '2026-10-15', months: 120,
  holdings: [{
    id: 'a1', name: 'Test ISA', kind: 'isa', value_today: '0.00', value_as_of: '2026-10-15', growth_pct: '7.00',
    monthly_contribution: '1000.00', history: [{ date: '2026-10-15', worth: '0.00' }],
    forecast: [{ date: '2026-10-15', worth: '0.00', paid_in: '0.00' }, { date: '2036-10-15', worth: '171051.73', paid_in: '120000.00' }],
  }],
  total: {
    value_today: '0.00', monthly_contribution: '1000.00', history: [{ date: '2026-10-15', worth: '0.00' }],
    forecast: [{ date: '2026-10-15', worth: '0.00', paid_in: '0.00' }, { date: '2036-10-15', worth: '171051.73', paid_in: '120000.00' }],
    answer: { months: 120, worth_about: '171000', paid_in: '120000' },
  },
  ...over,
})

describe('the graph sentence and inputs line', () => {
  it('G-1: the worked example', () => {
    expect(answerSentence(graph().total.answer)).toBe('In 10 years: worth about £171,000, paid in £120,000')
  })
  it('one holding: value today, contribution, growth', () => {
    expect(inputsLine(graph(), 'a1')).toBe('£0 today, £1,000 a month, 7% a year.')
  })
  it('G-2: all investments uses the API totals', () => {
    const two = graph({
      holdings: [graph().holdings[0], { ...graph().holdings[0], id: 'a2', name: 'Test Pension' }],
      total: { ...graph().total, value_today: '28000.00', monthly_contribution: '1000.00' },
    })
    expect(inputsLine(two, null)).toBe('2 investments, £28,000 today, £1,000 a month.')
  })
  it('one investment in "All"', () => {
    expect(inputsLine(graph({ total: { ...graph().total, value_today: '18000.00' } }), null))
      .toBe('1 investment, £18,000 today, £1,000 a month.')
  })
  it('the look-ahead options are 5, 10, 20 and 30 years', () => {
    expect(LOOK_AHEAD.map((o) => o.months)).toEqual([60, 120, 240, 360])
  })
})

describe('graph notes (G-5, G-6)', () => {
  it('one value only: the history note', () => {
    expect(graphStateNotes(graph(), 'a1').historyStarts).toBe(true)
  })
  it('several values: no note', () => {
    const h = graph().holdings[0]
    const g = graph({ holdings: [{ ...h, history: [{ date: '2026-01-01', worth: '1' }, { date: '2026-10-15', worth: '2' }] }] })
    expect(graphStateNotes(g, 'a1').historyStarts).toBe(false)
  })
  it('growth 0: the flat note, for one holding only', () => {
    const h = graph().holdings[0]
    expect(graphStateNotes(graph({ holdings: [{ ...h, growth_pct: '0.00' }] }), 'a1').flat).toBe(true)
    expect(graphStateNotes(graph(), 'a1').flat).toBe(false)
  })
})

describe('chart points (G-4)', () => {
  const series = {
    history: [{ date: '2026-01-15', worth: '100.00' }, { date: '2026-06-15', worth: '400.00' }, { date: '2026-10-15', worth: '900.00' }],
    forecast: [
      { date: '2026-10-15', worth: '900.00', paid_in: '900.00' },
      { date: '2026-11-15', worth: '1010.00', paid_in: '1000.00' },
    ],
  }
  it('history points are dots (worth), forecast points are dashed, joined at today', () => {
    const pts = chartPoints(series)
    expect(pts.map((p) => [p.date, p.history, p.entered, p.forecast, p.paidIn])).toEqual([
      ['2026-01-15', 100, true, undefined, undefined],
      ['2026-06-15', 400, true, undefined, undefined],
      ['2026-10-15', 900, true, 900, 900],
      ['2026-11-15', undefined, undefined, 1010, 1000],
    ])
    expect(pts[0].t).toBe(Date.parse('2026-01-15'))
  })
  it('the solid line reaches today at the value today, without a dot there unless entered that day', () => {
    const pts = chartPoints({ history: series.history.slice(0, 2), forecast: series.forecast })
    const today = pts.find((p) => p.date === '2026-10-15')!
    expect(today.history).toBe(900)
    expect(today.entered).toBeUndefined()
  })
  it('axis labels: Today, then +Ny ahead, month and year before', () => {
    const today = '2026-10-15'
    expect(axisLabel(Date.parse(today), today)).toBe('Today')
    expect(axisLabel(Date.parse('2031-10-15'), today)).toBe('+5y')
    expect(axisLabel(Date.parse('2026-04-15'), today)).toBe('Apr 2026')
  })
  it('the hidden table: Date, Worth, Paid in at 1, 5 and 10 years within the range', () => {
    const forecast = Array.from({ length: 121 }, (_, m) => ({ date: `m${m}`, worth: String(m * 10), paid_in: String(m) }))
    expect(tablePoints(forecast, 120).map((r) => r.date)).toEqual(['m12', 'm60', 'm120'])
    expect(tablePoints(forecast.slice(0, 61), 60).map((r) => r.date)).toEqual(['m12', 'm60'])
  })
})

describe('the default growth for holdings without their own rate', () => {
  it('follows the target form (wealth.growth) so the graph and projection agree', () => {
    expect(graphDefaultGrowth('3')).toBe(3)
    expect(graphDefaultGrowth('-100')).toBe(-100)
  })
  it('falls back to 5% when unset, unreadable or outside -100..50', () => {
    for (const raw of [null, '', 'abc', '60', '-101']) expect(graphDefaultGrowth(raw)).toBe(5)
  })
})

describe('the Update value modal', () => {
  const now = new Date('2026-10-11T12:00:00Z').getTime()
  it('names the holding, its last value and how long ago', () => {
    expect(lastValueLine(asset(), now)).toBe('Test ISA. Last value £18,000, 10 days ago.')
    expect(lastValueLine(asset({ valuations: [{ id: 'v', value: '500.50', valued_at: '2026-10-11' }] }), now))
      .toBe('Test ISA. Last value £500.50, today.')
    expect(lastValueLine(asset({ valuations: [{ id: 'v', value: '1', valued_at: '2026-10-10' }] }), now))
      .toBe('Test ISA. Last value £1, 1 day ago.')
  })
  it('accepts 0 or more, refuses anything else', () => {
    expect(parseValueToday('0')).toBe(0)
    expect(parseValueToday(' 18,500.25 ')).toBe(18500.25)
    for (const bad of ['', '-1', 'abc', '10000000.01']) expect(parseValueToday(bad)).toBeNull()
  })
})

describe('links into Wealth\'s investment form (ux on #217)', () => {
  it('edit one holding, or add an investment', () => {
    expect(wealthFormLink({ edit: 'a1' })).toBe('/networth?edit=a1')
    expect(wealthFormLink({ edit: 'a/b?c' })).toBe('/networth?edit=a%2Fb%3Fc')
    expect(wealthFormLink({ add: true })).toBe('/networth?add=investment')
  })
})

describe('value today comes from the API when it gives one', () => {
  it('a linked holding after a payment day is above its last entered value', () => {
    const paid = asset({ value_today: '19000.00' })
    expect(currentValue(paid)).toBe(19000)
    expect(investmentsTotal([paid])).toBe(19000)
  })
  it('falls back to the latest valuation for an older API', () => {
    expect(currentValue(asset())).toBe(18000)
    expect(currentValue(asset({ value_today: null }))).toBe(18000)
  })
})
