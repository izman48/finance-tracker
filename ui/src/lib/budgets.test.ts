import { describe, expect, it } from 'vitest'
import {
  cycleLabel,
  footText,
  lastCyclesText,
  limitError,
  money,
  paceFraction,
  reconciliationParts,
  statusText,
  meterLabel,
  LIMIT_ERROR,
  NOTHING_TICKED,
  SAVE_ERROR,
  SAVE_UNKNOWN,
  addOptions,
  claudeFooter,
  manageSubtitle,
  writeFailure,
  checkRows,
  suggestRows,
} from './budgets'
import { budget, budgetsResponse, reconciliation, suggestion } from './budgets.fixtures'

// Spending > Budgets (concept sections 4.2, 5, 9; T-09-6).
describe('money', () => {
  it('whole pounds without pence, pence only when there are some', () => {
    expect(money('212.00')).toBe('£212')
    expect(money(150)).toBe('£150')
    expect(money('150.40')).toBe('£150.40')
  })
})

describe('cycleLabel', () => {
  it('dates and days left', () => {
    expect(cycleLabel(budgetsResponse().cycle)).toBe('14 Oct to 11 Nov · 18 days left')
    expect(cycleLabel({ ...budgetsResponse().cycle, days_left: 1 })).toBe('14 Oct to 11 Nov · 1 day left')
  })
})

describe('status and row text (section 4.2, 4.3; status is never colour alone)', () => {
  it('pace words from the server status', () => {
    expect(statusText(budget({ status: 'on_pace' }))).toBe('On pace')
    expect(statusText(budget({ status: 'under_pace' }))).toBe('Under pace')
    expect(statusText(budget({ status: 'ahead_of_pace' }))).toBe('Ahead of pace')
  })

  it('"£x over" from the figures, in neutral words', () => {
    expect(statusText(budget({ status: 'over', limit_pounds: 150, spent: '162.00', over_by: '12.00' }))).toBe('£12 over')
    expect(statusText(budget({ status: 'over', limit_pounds: 150, spent: '150.40', over_by: '0.40' }))).toBe('£0.40 over')
    expect(statusText(budget({ status: null, paused: true }))).toBe('Paused')
  })

  it('no spending: £0 of £150 · Under pace (section 5)', () => {
    const b = budget({ limit_pounds: 150, spent: '0', status: 'under_pace' })
    expect(meterLabel(b, 18)).toBe('Groceries: £0 of £150, under pace, 18 days left')
  })

  it('the foot says what is left, or only the days once over', () => {
    expect(footText(budget(), 18)).toBe('£88 left · 18 days left')
    expect(footText(budget({ status: 'over', limit_pounds: 150, spent: '162.00', over_by: '12.00' }), 18)).toBe('18 days left')
  })

  it('the meter label names the category and carries the pace in words', () => {
    expect(meterLabel(budget({ status: 'over', category: 'Eating out', limit_pounds: 150, spent: '162.00', over_by: '12.00' }), 12)).toBe(
      'Eating out: £162 of £150, £12 over, 12 days left',
    )
  })
})

describe('paceFraction', () => {
  it('the pace tick sits at the API\'s pace figure over the limit, kept on the bar', () => {
    expect(paceFraction(budget({ limit_pounds: 300, pace_spent: '107.14' }))).toBeCloseTo(0.357, 3)
    expect(paceFraction(budget({ limit_pounds: 300, pace_spent: '400.00' }))).toBe(1)
    expect(paceFraction(budget({ limit_pounds: 0 }))).toBe(0)
  })
})

describe('reconciliationParts (section 3)', () => {
  it('shows the arithmetic as received', () => {
    expect(reconciliationParts(reconciliation())).toEqual({
      safe: '£480', left: '£268', other: '£160', headroom: '£52',
    })
  })

  it('a negative headroom keeps its sign', () => {
    const r = reconciliation({ headroom: '-30.00' })
    expect(reconciliationParts(r)?.headroom).toBe('−£30')
  })

  it('nothing to show without a reconciliation (no payday)', () => {
    expect(reconciliationParts(null)).toBeNull()
  })
})

describe('suggest sheet helpers (section 4.1)', () => {
  it('last 3 cycles, oldest first', () => {
    expect(lastCyclesText(suggestion())).toBe('Last 3 cycles: £276 · £291 · £262')
  })

  it('a limit is a whole number of pounds from 1 to 100,000 (BM3)', () => {
    expect(LIMIT_ERROR).toBe('Enter a whole number of pounds from 1 to 100,000.')
    for (const bad of ['', '0', '100001', '12.5', '-3', 'abc', '1e3']) expect(limitError(bad)).toBe(LIMIT_ERROR)
    for (const good of ['1', '280', '100000', ' 45 ']) expect(limitError(good)).toBeNull()
  })
})

describe('suggestRows and checkRows (section 4.1, BM3)', () => {
  it('rows start ticked with the suggested limit; no history means no row to tick and no limit', () => {
    const rows = suggestRows([suggestion(), suggestion({ category: 'Dining', last_cycles: [], suggested_limit: null })])
    expect(rows).toEqual([
      { category: 'Groceries', checked: true, limit: '280', available: true },
      { category: 'Dining', checked: false, limit: '', available: false },
    ])
  })

  it('only ticked rows are sent, each limit as a whole number', () => {
    const rows = [
      { category: 'Groceries', checked: true, limit: ' 300 ', available: true },
      { category: 'Transport', checked: false, limit: 'x', available: true },
    ]
    expect(checkRows(rows)).toEqual({ errors: {}, budgets: [{ category: 'Groceries', limit_pounds: 300 }], nothingTicked: false })
  })

  it('a bad limit on a ticked row blocks the save and names the row', () => {
    const rows = [{ category: 'Groceries', checked: true, limit: '12.5', available: true }]
    expect(checkRows(rows)).toEqual({ errors: { Groceries: LIMIT_ERROR }, budgets: [], nothingTicked: false })
  })

  it('nothing ticked: says so instead of doing nothing (ux on #153)', () => {
    expect(NOTHING_TICKED).toBe('Tick at least one budget to save.')
    const rows = [{ category: 'Groceries', checked: false, limit: '300', available: true }]
    expect(checkRows(rows)).toEqual({ errors: {}, budgets: [], nothingTicked: true })
  })
})

describe('Manage budgets helpers (section 13)', () => {
  it('the subtitle names the cycle', () => {
    expect(manageSubtitle(budgetsResponse().cycle)).toBe(
      'Pay cycle 14 Oct to 11 Nov. Changes apply to this cycle and the ones after.',
    )
  })

  it('the Claude footer counts the budgets Claude changed, with the latest date', () => {
    expect(claudeFooter([budget()])).toBeNull()
    const marked = [
      budget({ changed_by_claude: { audit_id: 'a1', at: '2026-10-10T09:00:00Z' } }),
      budget({ id: 'b2', changed_by_claude: { audit_id: 'a2', at: '2026-10-12T09:00:00Z' } }),
    ]
    expect(claudeFooter(marked)).toBe('Claude changed 2 budgets on 12 Oct')
    expect(claudeFooter(marked.slice(0, 1))).toBe('Claude changed 1 budget on 10 Oct')
  })

  it('Add budget offers only categories with no budget (paused counts as having one) (BM2)', () => {
    const budgets = [budget({ category: 'Groceries' }), budget({ id: 'p', category: 'Hobbies', paused: true, status: null })]
    expect(addOptions(['Transport', 'Groceries', 'Hobbies', 'Eating out', 'Uncategorized'], budgets)).toEqual([
      'Eating out',
      'Transport',
    ])
  })

  it('write failures map to the spec copy, never the server text (BM2, BM11)', () => {
    const fail = (status: number | undefined, detail?: string) =>
      status === undefined ? new Error('timed out') : { response: { status, data: { detail } } }
    expect(writeFailure(fail(422, 'That category already has a budget.'), 'Groceries')).toBe(
      'You already have a budget for Groceries.',
    )
    expect(writeFailure(fail(422, 'Budgets can only use your existing categories.'), 'Groceries')).toBe(SAVE_ERROR)
    expect(writeFailure(fail(500), 'Groceries')).toBe(SAVE_ERROR)
    expect(writeFailure(fail(undefined), 'Groceries')).toBe(SAVE_UNKNOWN)
    expect(SAVE_ERROR).toBe("Couldn't save your budgets. Nothing was changed. Try again.")
    expect(SAVE_UNKNOWN).toBe("Couldn't confirm that. Your budgets may have been saved; check them before you try again.")
  })
})
