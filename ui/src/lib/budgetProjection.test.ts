import { describe, expect, it } from 'vitest'
import {
  budgetTooltip,
  dipSentence,
  paydayFigures,
  projectionNote,
  projectionUnavailable,
  withBudgetLine,
  type BudgetProjection,
} from './budgetProjection'

// Budgets on Cashflow, the simple rule (T-09-14/15, owner 2026-10-12): the
// dotted line is the scheduled line less the budgets, over the whole chart.
// Every figure is the API's; the UI does no money arithmetic.
const projection = (over: Partial<BudgetProjection> = {}): BudgetProjection => ({
  payday: '2026-10-24',
  scheduled_balance: '480.00',
  after_budgets_balance: '221.00',
  series: [
    { date: '2026-10-12', balance: '1860.00' },
    { date: '2026-10-23', balance: '221.00' },
    { date: '2026-10-24', balance: '2721.00' },
  ],
  ...over,
})

describe('the payday line', () => {
  it('two figures as received; a negative one is marked', () => {
    expect(paydayFigures(projection())).toEqual({
      scheduled: { amount: '£480', negative: false },
      afterBudgets: { amount: '£221', negative: false },
    })
    expect(paydayFigures(projection({ after_budgets_balance: '-30.00' })).afterBudgets).toEqual({ amount: '−£30', negative: true })
  })

  it('only the two figures exist: no pace, headroom or difference', () => {
    expect(Object.keys(paydayFigures(projection())).sort()).toEqual(['afterBudgets', 'scheduled'])
  })

  it('BC6: the dip note when the dotted line goes below £0', () => {
    expect(dipSentence(projection())).toBeNull()
    const dips = projection({ series: [{ date: '2026-10-20', balance: '10.00' }, { date: '2026-10-21', balance: '-5.00' }] })
    expect(dipSentence(dips)).toBe("If you spend all your budgets, you'd dip below £0 on 21 Oct.")
  })
})

describe('budgetTooltip', () => {
  it('both values in whole pounds, as the chart has them', () => {
    expect(budgetTooltip(480.4, 212)).toBe('£480 scheduled · £212 after budgets')
    expect(budgetTooltip(-30, -242)).toBe('−£30 scheduled · −£242 after budgets')
  })
})

describe('projectionNote (BC2, BC3)', () => {
  it('no budgets: nothing at all; no payday: the set-payday line', () => {
    expect(projectionNote(null, 'no_budgets')).toBeNull()
    expect(projectionNote(null, undefined)).toBeNull()
    expect(projectionNote(null, 'no_payday')).toBe('Set your payday on Commitments to see your budgets on this chart.')
    expect(projectionNote(projection(), null)).toBeNull()
  })
})

describe('projectionUnavailable (BC8)', () => {
  it('our own line when the server could not compute it; nothing otherwise', () => {
    expect(projectionUnavailable('unavailable')).toBe("Couldn't load your budget line.")
    for (const r of ['no_budgets', 'no_payday', null, undefined] as const) expect(projectionUnavailable(r)).toBeNull()
    expect(projectionNote(null, 'unavailable')).toBeNull()
  })
})

describe('withBudgetLine', () => {
  it('adds the dotted line\'s value on its dates: the whole chart, past payday', () => {
    const timeline = [
      { date: '2026-10-12', balance: 1860 },
      { date: '2026-10-23', balance: 480 },
      { date: '2026-10-24', balance: 2980 },
    ]
    expect(withBudgetLine(timeline, projection())).toEqual([
      { date: '2026-10-12', balance: 1860, budget: 1860 },
      { date: '2026-10-23', balance: 480, budget: 221 },
      { date: '2026-10-24', balance: 2980, budget: 2721 },
    ])
    expect(withBudgetLine(timeline, null)).toBe(timeline)
    expect(withBudgetLine([{ date: '2026-12-01', balance: 1 }], projection())).toEqual([{ date: '2026-12-01', balance: 1, budget: null }])
  })
})
