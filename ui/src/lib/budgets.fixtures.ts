import type { Budget, BudgetsResponse, BudgetSuggestion, Reconciliation } from './budgets'

/** GET /budgets shaped like T-09-2's schemas (#150). */
export function budget(over: Partial<Budget> = {}): Budget {
  return {
    id: 'b1',
    category: 'Groceries',
    limit_pounds: 300,
    paused: false,
    created_via: 'web',
    spent: '212.00',
    pace_spent: '107.14',
    over_by: '0.00',
    status: 'on_pace',
    changed_by_claude: null,
    ...over,
  }
}

export function budgetsResponse(over: Partial<BudgetsResponse> = {}): BudgetsResponse {
  return {
    cycle: { start: '2026-10-14', end: '2026-11-11', days_total: 28, days_left: 18, fallback: false },
    budgets: [
      budget(),
      budget({ id: 'b2', category: 'Eating out', limit_pounds: 150, spent: '162.00', pace_spent: '53.57', over_by: '12.00', status: 'over' }),
      budget({ id: 'b3', category: 'Transport', limit_pounds: 90, spent: '48.00', pace_spent: '32.14', status: 'under_pace' }),
    ],
    other_spending: '392.00',
    total_spent: '814.00',
    not_counted: { commitments: '1203.00', transfers: '600.00', card_payoffs: '340.00', financed: '0.00' },
    reconciliation: reconciliation(),
    ...over,
  }
}

export function suggestion(over: Partial<BudgetSuggestion> = {}): BudgetSuggestion {
  return {
    category: 'Groceries',
    last_cycles: [
      { start: '2026-07-14', end: '2026-08-13', spent: '276.00' },
      { start: '2026-08-14', end: '2026-09-13', spent: '291.00' },
      { start: '2026-09-14', end: '2026-10-13', spent: '262.00' },
    ],
    suggested_limit: 280,
    current_limit: null,
    ...over,
  }
}

export function reconciliation(over: Partial<Reconciliation> = {}): Reconciliation {
  return { safe_to_spend: '480.00', budgets_left: '268.00', other_at_pace: '160.00', headroom: '52.00', ...over }
}
