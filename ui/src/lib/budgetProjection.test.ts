import { describe, expect, it } from 'vitest'
import {
  differenceSentence,
  dipSentence,
  projectionNote,
  stripFigures,
  stripTitle,
  withBudgetLine,
  type BudgetProjection,
} from './budgetProjection'

// Budgets on Cashflow (concept section 12, 12a; BC1-BC12; T-09-8). The UI does no money arithmetic.
const projection = (over: Partial<BudgetProjection> = {}): BudgetProjection => ({
  payday: '2026-10-24',
  scheduled_balance: '480.00',
  stick_to_budgets_balance: '52.00',
  current_pace_balance: '-30.00',
  headroom: '52.00',
  difference: '0.00',
  series: [
    { date: '2026-10-12', balance: '1860.00' },
    { date: '2026-10-23', balance: '52.00' },
  ],
  ...over,
})

describe('the payday strip', () => {
  it('title names payday', () => {
    expect(stripTitle(projection())).toBe('Your balance on payday (24 Oct), before your pay arrives')
  })

  it('BC4/BC5: three figures as received; only a balance below £0 is negative-toned', () => {
    expect(stripFigures(projection())).toEqual([
      { label: 'Scheduled only', explain: 'Bills and plans, no day-to-day spending', amount: '£480', negative: false, line: 'solid' },
      { label: 'If you stick to your budgets', explain: 'Remaining budgets, other spending at your pace', amount: '£52', negative: false, line: 'dotted' },
      { label: 'At your current pace', explain: 'Everything at the rate so far', amount: '−£30', negative: true, line: 'none' },
    ])
  })

  it('BC12: the difference sentence only when the two figures differ, with the API\'s numbers', () => {
    expect(differenceSentence(projection())).toBeNull()
    expect(differenceSentence(projection({ stick_to_budgets_balance: '302.00', difference: '250.00' }))).toBe(
      'Your headroom on Spending (£52) starts from your safe to spend; this starts from your forecast balance, so they differ by £250.',
    )
    expect(differenceSentence(projection({ difference: '-12.50' }))).toBe(
      'Your headroom on Spending (£52) starts from your safe to spend; this starts from your forecast balance, so they differ by £12.50.',
    )
  })

  it('BC6: the dip note when the dotted line goes below £0 before payday', () => {
    expect(dipSentence(projection())).toBeNull()
    const dips = projection({ series: [{ date: '2026-10-20', balance: '10.00' }, { date: '2026-10-21', balance: '-5.00' }] })
    expect(dipSentence(dips)).toBe(
      'If you spent every budget in full and kept your usual other spending, you would dip below £0 on 21 Oct.',
    )
  })
})

describe('projectionNote (BC2, BC3)', () => {
  it('no budgets: nothing at all; no payday: the set-payday line', () => {
    expect(projectionNote(null, 'no_budgets')).toBeNull()
    expect(projectionNote(null, undefined)).toBeNull()
    expect(projectionNote(null, 'no_payday')).toBe('Set your payday on Commitments to see how your budgets affect your balance.')
    expect(projectionNote(projection(), null)).toBeNull()
  })
})

describe('withBudgetLine', () => {
  it('adds the dotted line\'s value on its dates only (it stops at payday)', () => {
    const timeline = [
      { date: '2026-10-12', balance: 1860 },
      { date: '2026-10-23', balance: 480 },
      { date: '2026-10-24', balance: 2980 },
    ]
    expect(withBudgetLine(timeline, projection())).toEqual([
      { date: '2026-10-12', balance: 1860, budget: 1860 },
      { date: '2026-10-23', balance: 480, budget: 52 },
      { date: '2026-10-24', balance: 2980, budget: null },
    ])
    expect(withBudgetLine(timeline, null)).toBe(timeline)
  })
})
