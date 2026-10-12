import { describe, expect, it } from 'vitest'
import {
  cycleLabel,
  footText,
  lastCyclesText,
  limitError,
  money,
  paceFraction,
  budgetsBox,
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
  focusAfterWrite,
  editAllEntries,
  editAllTotal,
  suggestDiff,
  budgetNudgeId,
  homeBudgetLine,
  checkRows,
  suggestRows,
} from './budgets'
import { budget, budgetsResponse, summaryThisCycle, suggestion } from './budgets.fixtures'

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

describe('budgetsBox (concept 12a; BX1-BX4, BX6)', () => {
  it('BX1: the total, spent and left, in whole pounds as received, and the bills line', () => {
    expect(budgetsBox(summaryThisCycle())).toEqual({
      line1: '£890 this cycle. Spent £631, £259 left.',
      line2: 'Bills are already in your safe to spend. Budgets are for your day-to-day spending.',
      paused: null,
    })
  })
  it('BX2: the first over budget is appended to line 1', () => {
    const s = summaryThisCycle({ first_over: { category: 'Eating out', over_by: '12.40' } })
    expect(budgetsBox(s).line1).toBe('£890 this cycle. Spent £631, £259 left. Eating out is £12 over.')
  })
  it('BX3: paused budgets, singular and plural', () => {
    expect(budgetsBox(summaryThisCycle({ paused_count: 1 })).paused).toBe("1 paused budget isn't counted.")
    expect(budgetsBox(summaryThisCycle({ paused_count: 2 })).paused).toBe("2 paused budgets aren't counted.")
  })
  it('BX4: every budget paused', () => {
    const all = summaryThisCycle({ total_limit: '0', spent: '0', left: '0', paused_count: 3 })
    expect(budgetsBox(all, true)).toEqual({
      line1: 'All your budgets are paused, so none are counted.',
      line2: 'Bills are already in your safe to spend. Budgets are for your day-to-day spending.',
      paused: null,
    })
  })
  it('BX6: no headroom, safe-to-spend amount or arithmetic', () => {
    const t = Object.values(budgetsBox(summaryThisCycle({ paused_count: 2 }))).join(' ')
    expect(t).not.toMatch(/headroom|[−=]/)
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

describe('focusAfterWrite (BM19: focus never falls to body)', () => {
  it('an edit returns to that row\'s Edit button', () => {
    expect(focusAfterWrite('edit', 'b1', true)).toBe('[data-focus="edit-b1"]')
  })
  it('an add returns to + Add budget', () => {
    expect(focusAfterWrite('add', null, true)).toBe('[data-focus="add"]')
  })
  it('a remove returns to + Add budget, or the sheet itself when Add is disabled', () => {
    expect(focusAfterWrite('remove', 'b1', true)).toBe('[data-focus="add"]')
    expect(focusAfterWrite('remove', 'b1', false)).toBe('[role="dialog"]')
  })
})

describe('Edit all (section 13, BM4)', () => {
  const budgets = [budget({ id: 'b1', category: 'Groceries', limit_pounds: 300 }), budget({ id: 'b2', category: 'Eating out', limit_pounds: 150 })]

  it('the running total, against the total before', () => {
    expect(editAllTotal(budgets, { b1: '300', b2: '150' })).toBe('Total per cycle £450')
    expect(editAllTotal(budgets, { b1: '320', b2: '160' })).toBe('Total per cycle £480 (was £450)')
    // A field mid-edit (invalid) counts at its old limit until it's valid.
    expect(editAllTotal(budgets, { b1: '3x', b2: '160' })).toBe('Total per cycle £460 (was £450)')
  })

  it('sends only the changed limits, all at once; any bad field blocks the save', () => {
    expect(editAllEntries(budgets, { b1: '320', b2: '150' })).toEqual({
      errors: {},
      budgets: [{ category: 'Groceries', limit_pounds: 320 }],
    })
    expect(editAllEntries(budgets, { b1: '0', b2: '160' })).toEqual({ errors: { b1: LIMIT_ERROR }, budgets: [] })
  })
})

describe('Suggest again (section 13, BM6)', () => {
  const budgets = [
    budget({ id: 'b1', category: 'Groceries', limit_pounds: 300 }),
    budget({ id: 'b2', category: 'Eating out', limit_pounds: 150 }),
    budget({ id: 'b3', category: 'Transport', limit_pounds: 80 }),
  ]
  const suggestions = [
    suggestion({ category: 'Groceries', suggested_limit: 280, current_limit: 300 }),
    suggestion({ category: 'Eating out', suggested_limit: 150, current_limit: 150 }),
    suggestion({ category: 'Transport', suggested_limit: 80, current_limit: 80 }),
    suggestion({ category: 'Health & beauty', suggested_limit: 40, current_limit: null }),
    suggestion({ category: 'Dining', suggested_limit: null, reason: 'not_enough_history', current_limit: null }),
  ]

  it('changes and new budgets are shown; unchanged ones are counted, not listed', () => {
    const diff = suggestDiff(suggestions, budgets)
    expect(diff.rows.map((r) => [r.category, r.change])).toEqual([
      ['Groceries', 'Now £300 → suggested £280'],
      ['Health & beauty', 'New'],
    ])
    expect(diff.unchanged).toBe(2)
    expect(diff.summary).toBe('1 change and 1 new budget. Nothing is saved until you press Save.')
  })

  it('rows start ticked with the suggested limit, and save as one upsert', () => {
    const diff = suggestDiff(suggestions, budgets)
    expect(checkRows(diff.rows)).toEqual({
      errors: {},
      budgets: [{ category: 'Groceries', limit_pounds: 280 }, { category: 'Health & beauty', limit_pounds: 40 }],
      nothingTicked: false,
    })
  })

  it('nothing to change: says so', () => {
    const same = [suggestion({ category: 'Groceries', suggested_limit: 300, current_limit: 300 })]
    expect(suggestDiff(same, budgets.slice(0, 1)).summary).toBe('Your budgets already match the suggestions.')
  })
})

describe('the Home line (section 3, BM7)', () => {
  it('"4 of 5 on pace · Eating out is £12 over", or without the over part', () => {
    expect(homeBudgetLine({ budget_count: 5, on_pace_count: 4, first_over: { category: 'Eating out', over_by: '12.00' } })).toEqual({
      count: '4 of 5',
      rest: 'on pace · Eating out is £12 over',
    })
    expect(homeBudgetLine({ budget_count: 3, on_pace_count: 3, first_over: null })).toEqual({ count: '3 of 3', rest: 'on pace' })
  })

  it('no budgets: no line', () => {
    expect(homeBudgetLine({ budget_count: 0, on_pace_count: 0, first_over: null })).toBeNull()
    expect(homeBudgetLine(undefined)).toBeNull()
  })
})

describe('budgetNudgeId', () => {
  it('a budget nudge is dismissed on the server; others stay local', () => {
    expect(budgetNudgeId('budget-1b0c2d3e-0000-4000-8000-000000000001')).toBe('1b0c2d3e-0000-4000-8000-000000000001')
    expect(budgetNudgeId('cash_drag')).toBeNull()
    expect(budgetNudgeId('budget-../../x')).toBeNull()
  })
})
