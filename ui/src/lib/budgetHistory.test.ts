import { describe, expect, it } from 'vitest'
import {
  barHeight,
  budgetLimitText,
  chartMax,
  cycleBarLabel,
  headline,
  keptText,
  nowBarLabel,
  nowSpent,
  showMore,
  slotLabel,
  trendText,
  type HistoryBudget,
  type HistoryCycle,
  type HistoryResponse,
  type HistorySlot,
} from './budgetHistory'
import type { Budget } from './budgets'

// Spending > Budgets > Past cycles (concept 14; BH1-BH14; T-09-9). Every count,
// verdict and trend is the server's; the UI only words them.
const cycle = (over: Partial<HistoryCycle> = {}): HistoryCycle => ({
  start: '2026-08-02', end: '2026-08-29', total_limit: '450', total_spent: '420.50', on_target: true, ...over,
})
const slot = (over: Partial<HistorySlot> = {}): HistorySlot => ({
  start: '2026-08-02', end: '2026-08-29', existed: true, paused: false, limit_pounds: 300, spent: '276.00', kept: true, ...over,
})
const budget = (over: Partial<HistoryBudget> = {}): HistoryBudget => ({
  budget_id: 'b1', category: 'Groceries', kept: 4, counted: 6, usually: '290.33', cycles: [slot()], ...over,
})
const history = (over: Partial<HistoryResponse> = {}): HistoryResponse => ({
  cycles: [cycle()], budgets: [budget()], on_target: 5, counted: 6, trend: null, has_more: false, ...over,
})

describe('headline (BH1, BH13)', () => {
  it('k of n from the server', () => {
    expect(headline(history())).toBe('On target in 5 of the last 6 cycles')
    expect(headline(history({ on_target: 1, counted: 1 }))).toBe('On target in 1 of 1 cycle so far')
    expect(headline(history({ on_target: 0, counted: 1 }))).toBe('On target in 0 of 1 cycle so far')
  })
  it('every cycle shown had all budgets paused', () => {
    expect(headline(history({ on_target: 0, counted: 0 }))).toBe('No cycles counted yet: your budgets were paused.')
  })
})

describe('trendText (BH6)', () => {
  it('under 6 cycles: the trend waits', () => {
    expect(trendText(null)).toBe('Trend appears after 6 completed cycles.')
  })
  it('lower, higher, about the same', () => {
    expect(trendText({ difference: '42', direction: 'lower' })).toBe(
      'Your budgeted spending is about £42 a cycle lower than in the 3 cycles before.')
    expect(trendText({ difference: '15', direction: 'higher' })).toBe(
      'Your budgeted spending is about £15 a cycle higher than in the 3 cycles before.')
    expect(trendText({ difference: '4', direction: 'same' })).toBe(
      'Your budgeted spending is about the same as in the 3 cycles before.')
  })
})

describe('bar names (BH11)', () => {
  it('a cycle: dates, spent, limit and the result; over has no amount computed here', () => {
    expect(cycleBarLabel(cycle())).toBe('2 Aug to 29 Aug: spent £420.50 of £450, within your limits')
    expect(cycleBarLabel(cycle({ total_spent: '480', on_target: false }))).toBe('2 Aug to 29 Aug: spent £480 of £450, over your limits')
    expect(cycleBarLabel(cycle({ on_target: null }))).toBe('2 Aug to 29 Aug: all budgets paused, not counted')
  })
  it('a budget slot: kept, over, paused, before it existed', () => {
    expect(slotLabel(slot())).toBe('2 Aug to 29 Aug: spent £276 of £300, within your limit')
    expect(slotLabel(slot({ spent: '318', kept: false }))).toBe('2 Aug to 29 Aug: spent £318 of £300, over your limit')
    expect(slotLabel(slot({ paused: true, kept: null }))).toBe('2 Aug to 29 Aug: paused, not counted')
    expect(slotLabel(slot({ existed: false, limit_pounds: null, spent: null, kept: null }))).toBe('2 Aug to 29 Aug: no budget yet')
  })
  it('BH14: the current cycle is named without an amount', () => {
    expect(nowBarLabel('2026-10-24')).toBe('24 Oct to now: this cycle, still running, not counted')
  })
})

describe('per budget (BH2, BH4, BH13)', () => {
  it('Kept k of n, or paused throughout', () => {
    expect(keptText(budget())).toBe('Kept 4 of 6')
    expect(keptText(budget({ kept: 2, counted: 3 }))).toBe('Kept 2 of 3')
    expect(keptText(budget({ kept: 0, counted: 0 }))).toBe('Paused in these cycles')
  })
  it('the latest limit shown and usually, when there is one', () => {
    const b = budget({ cycles: [slot({ limit_pounds: 250 }), slot({ limit_pounds: 300 }), slot({ existed: false, limit_pounds: null })] })
    expect(budgetLimitText(b)).toBe('Limit £300 · usually £290')
    expect(budgetLimitText(budget({ usually: null }))).toBe('Limit £300')
    expect(budgetLimitText(budget({ usually: '290.50' }))).toBe('Limit £300 · usually £291') // whole pounds (ux on #165)
  })
  it('BH15: the row\'s own limit from the server when it sends one', () => {
    expect(budgetLimitText(budget({ limit_pounds: 350, cycles: [slot({ limit_pounds: 300 })] }))).toBe('Limit £350 · usually £290')
  })
})

describe('bar heights', () => {
  it('scaled to the tallest bar or limit, with headroom above it', () => {
    const max = chartMax([100, 300, 250])
    expect(max).toBeCloseTo(336)
    expect(barHeight(300, max)).toBeCloseTo(89.29, 1)
    expect(barHeight(0, max)).toBe(0)
    expect(barHeight(10, 0)).toBe(0)
  })
})

describe('nowSpent: the current bar\'s height only (never shown as a figure)', () => {
  it('tracked budgets only', () => {
    const b = (spent: string, paused = false) => ({ spent, paused }) as Budget
    expect(nowSpent([b('100.10'), b('50.20'), b('999', true)])).toBeCloseTo(150.3)
  })
})

describe('showMore (BH10, BH14)', () => {
  it('offered while the server has more and fewer than 12 are shown', () => {
    expect(showMore(history({ has_more: true, cycles: Array(6).fill(cycle()) }))).toBe(true)
    expect(showMore(history({ has_more: false, cycles: Array(6).fill(cycle()) }))).toBe(false)
    expect(showMore(history({ has_more: true, cycles: Array(12).fill(cycle()) }))).toBe(false)
  })
})
