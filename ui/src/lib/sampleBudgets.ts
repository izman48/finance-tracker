/** Sample budgets for demo mode (T-11-8). Computed from the sample ledger
 *  with the API's rules (api/app/services/budgets.py and budget_history.py),
 *  so every figure reconciles with the sample Spending tab: spend is
 *  purchases (not commitments, transfers or card payoffs) per category in
 *  the pay cycle, pace is the limit times the share of the cycle gone, and a
 *  budget is kept when spend is at or under its limit. Synthetic figures. */

export interface BudgetLedgerTx {
  category: string
  amount: number
  daysAgo: number
  kind: 'purchase' | 'commitment' | 'transfer' | 'card_payoff' | 'other'
}

interface SampleBudget { id: string; category: string; limit_pounds: number; paused: boolean }

const SAMPLE_BUDGETS: SampleBudget[] = [
  { id: 'sb1', category: 'Groceries', limit_pounds: 320, paused: false },
  { id: 'sb2', category: 'Eating out', limit_pounds: 90, paused: false },
  { id: 'sb3', category: 'Transport', limit_pounds: 30, paused: false },
  { id: 'sb4', category: 'Shopping', limit_pounds: 120, paused: true },
]
const CYCLE_DAYS = 30
const PACE_BAND = 0.1
const HISTORY_CYCLES = 5 // complete cycles the six-month ledger covers

const round2 = (n: number) => Math.round(n * 100) / 100
const money = (n: number) => round2(n).toFixed(2)
const isoDaysAgo = (days: number) => {
  const d = new Date()
  d.setDate(d.getDate() - days)
  d.setHours(9, 0, 0, 0)
  return d.toISOString().slice(0, 10)
}

/** Purchases per category with daysAgo in [toAgo, fromAgo]. */
function spendByCategory(ledger: BudgetLedgerTx[], fromAgo: number, toAgo: number) {
  const out = new Map<string, number>()
  for (const tx of ledger) {
    if (tx.kind !== 'purchase' || tx.daysAgo > fromAgo || tx.daysAgo < toAgo) continue
    out.set(tx.category, (out.get(tx.category) ?? 0) + tx.amount)
  }
  return out
}

function status(spent: number, pace: number, limit: number) {
  if (spent > limit) return 'over' as const
  if (spent > pace * (1 + PACE_BAND)) return 'ahead_of_pace' as const
  if (spent < pace * (1 - PACE_BAND)) return 'under_pace' as const
  return 'on_pace' as const
}

/** GET /budgets. `paydayAgo` is how many days ago the sample salary landed. */
export function sampleBudgetList(ledger: BudgetLedgerTx[], paydayAgo: number, includeCategories: boolean) {
  const elapsed = paydayAgo + 1
  const spend = spendByCategory(ledger, paydayAgo, 0)
  const rows = SAMPLE_BUDGETS.map((b) => {
    const spent = round2(spend.get(b.category) ?? 0)
    const pace = round2(b.limit_pounds * (elapsed / CYCLE_DAYS))
    return {
      id: b.id, category: b.category, limit_pounds: b.limit_pounds, paused: b.paused, created_via: 'web' as const,
      spent: money(spent), pace_spent: money(pace), over_by: money(Math.max(0, spent - b.limit_pounds)),
      status: b.paused ? null : status(spent, pace, b.limit_pounds), changed_by_claude: null,
    }
  })
  const counting = rows.filter((r) => !r.paused)
  const tracked = new Set(counting.map((r) => r.category))
  const total = [...spend.values()].reduce((t, v) => t + v, 0)
  const other = [...spend.entries()].filter(([c]) => !tracked.has(c)).reduce((t, [, v]) => t + v, 0)
  const over = counting.filter((r) => r.status === 'over').sort((a, b) => Number(b.over_by) - Number(a.over_by))
  const firstOver = over.length ? { category: over[0].category, over_by: over[0].over_by } : null
  const excluded = (kind: BudgetLedgerTx['kind']) =>
    money(ledger.filter((tx) => tx.kind === kind && tx.daysAgo <= paydayAgo).reduce((t, tx) => t + tx.amount, 0))
  return {
    cycle: {
      start: isoDaysAgo(paydayAgo), end: isoDaysAgo(paydayAgo - (CYCLE_DAYS - 1)),
      days_total: CYCLE_DAYS, days_left: CYCLE_DAYS - elapsed, fallback: false,
    },
    budgets: rows,
    other_spending: money(other),
    total_spent: money(total),
    not_counted: {
      commitments: excluded('commitment'), transfers: excluded('transfer'),
      card_payoffs: excluded('card_payoff'), financed: '0.00',
    },
    summary_this_cycle: {
      total_limit: money(counting.reduce((t, r) => t + r.limit_pounds, 0)),
      spent: money(counting.reduce((t, r) => t + Number(r.spent), 0)),
      left: money(counting.reduce((t, r) => t + Math.max(0, r.limit_pounds - Number(r.spent)), 0)),
      first_over: firstOver,
      paused_count: rows.length - counting.length,
    },
    summary: {
      budget_count: counting.length,
      on_pace_count: counting.filter((r) => r.status === 'under_pace' || r.status === 'on_pace').length,
      first_over: firstOver,
    },
    budgetable_categories: includeCategories
      ? [...new Set(ledger.filter((tx) => tx.kind === 'purchase').map((tx) => tx.category))].sort()
      : null,
  }
}

/** The sample's monthly budget total for the projection's "My budgets". */
export const SAMPLE_BUDGETS_MONTHLY = SAMPLE_BUDGETS.filter((b) => !b.paused).reduce((t, b) => t + b.limit_pounds, 0)

/** GET /budgets/history: the completed cycles, oldest first, with today's
 *  limits throughout (the sample has no change log). */
export function sampleBudgetHistory(ledger: BudgetLedgerTx[], paydayAgo: number, cycles: number) {
  const shown = Math.min(Math.max(1, cycles), HISTORY_CYCLES)
  const ranges = Array.from({ length: shown }, (_, i) => {
    const k = shown - i // oldest first
    const fromAgo = paydayAgo + CYCLE_DAYS * k
    return { fromAgo, toAgo: fromAgo - (CYCLE_DAYS - 1) }
  })
  const spends = ranges.map((r) => spendByCategory(ledger, r.fromAgo, r.toAgo))
  const budgets = [...SAMPLE_BUDGETS].sort((a, b) => a.category.localeCompare(b.category)).map((b) => {
    const slots = ranges.map((r, i) => {
      const spent = round2(spends[i].get(b.category) ?? 0)
      return {
        start: isoDaysAgo(r.fromAgo), end: isoDaysAgo(r.toAgo), existed: true, paused: b.paused,
        limit_pounds: b.limit_pounds, spent: money(spent), kept: b.paused ? null : spent <= b.limit_pounds,
      }
    })
    const counted = slots.filter((s) => s.kept !== null)
    return {
      budget_id: b.id, category: b.category, limit_pounds: b.limit_pounds, removed: false,
      kept: counted.filter((s) => s.kept).length, counted: counted.length,
      usually: counted.length ? money(counted.reduce((t, s) => t + Number(s.spent), 0) / counted.length) : null,
      cycles: slots,
    }
  })
  const overall = ranges.map((r, i) => {
    const counted = budgets.map((b) => b.cycles[i]).filter((s) => !s.paused)
    const limit = counted.reduce((t, s) => t + s.limit_pounds, 0)
    const spent = round2(counted.reduce((t, s) => t + Number(s.spent), 0))
    return { start: isoDaysAgo(r.fromAgo), end: isoDaysAgo(r.toAgo), total_limit: String(limit), total_spent: money(spent), on_target: spent <= limit }
  })
  return {
    cycles: overall,
    budgets,
    on_target: overall.filter((c) => c.on_target).length,
    counted: overall.length,
    trend: null, // needs 6 completed cycles; the sample has 5
    has_more: false,
  }
}
