import type { PlanBudget, PlanResponse } from './plan'

/** GET /plan shaped like the T-24-4 contract. Synthetic names and amounts;
 *  the lines add up: 3,100.00 − 989.49 − 620.50 = 1,490.01 (Eating out counts
 *  at £370.50: £330.50 spent + £40.00 coming up, over its £300 limit). */
export function planBudget(over: Partial<PlanBudget> = {}): PlanBudget {
  return {
    budget_id: 'pb2', category: 'Groceries', limit: '250.00', spent: '120.00', coming_up: '0.00',
    status: 'under_pace', over_by: '0.00', commitments: [], commitment_count: 0, other_purchases: '120.00', ...over,
  }
}

export function planResponse(over: Partial<PlanResponse> = {}): PlanResponse {
  return {
    cycle: { start: '2026-10-30', end: '2026-11-29', days_left: 16 },
    income: {
      total: '3100.00', received_count: 1, expected_count: 1,
      items: [
        { id: 'in1', label: 'Salary', date: '2026-10-30', amount: '2800.00', status: 'received', transaction_id: 'tx-sal' },
        { id: 'in2', label: 'Side job', date: '2026-11-28', amount: '300.00', status: 'expected', transaction_id: null },
      ],
    },
    fixed: {
      total: '989.49', paid: '959.99', to_pay: '29.50', paid_count: 2, count: 4,
      groups: [
        { source: 'commitment', category: 'Housing', total: '950.00', paid_count: 1, count: 1, items: [
          { source: 'commitment', commitment_id: 'c-rent', label: 'Rent', due_date: '2026-11-01', amount: '950.00', status: 'paid', transaction_id: 'tx-rent' },
        ] },
        { source: 'commitment', category: 'Subscriptions', total: '14.49', paid_count: 1, count: 2, items: [
          { source: 'commitment', commitment_id: 'c-str', label: 'Streamly', due_date: '2026-11-04', amount: '9.99', status: 'paid', transaction_id: 'tx-str' },
          { source: 'commitment', commitment_id: 'c-cb', label: 'Cloudbox', due_date: '2026-11-21', amount: '4.50', status: 'due', transaction_id: null },
          { source: 'commitment', commitment_id: 'c-pass', label: 'Annual pass', due_date: null, amount: '120.00', status: 'not_due_this_cycle', transaction_id: null },
        ] },
        { source: 'commitment', category: null, total: '25.00', paid_count: 0, count: 1, items: [
          { source: 'commitment', commitment_id: 'c-gym', label: 'Gym club', due_date: '2026-11-20', amount: '25.00', status: 'due', transaction_id: null },
        ] },
      ],
    },
    budgets: {
      limits_total: '550.00', planned_total: '620.50', spent: '450.50', coming_up: '40.00', count: 2,
      items: [
        planBudget({
          budget_id: 'pb1', category: 'Eating out', limit: '300.00', spent: '330.50', coming_up: '40.00',
          status: 'over', over_by: '30.50', other_purchases: '310.50',
          commitments: [
            { commitment_id: 'c-pz', label: 'Pizza club', date: '2026-11-06', amount: '20.00', status: 'paid', transaction_id: 'tx-pz1' },
            { commitment_id: 'c-pz', label: 'Pizza club', date: '2026-11-20', amount: '20.00', status: 'due', transaction_id: null },
            { commitment_id: 'c-pz', label: 'Pizza club', date: '2026-11-27', amount: '20.00', status: 'due', transaction_id: null },
          ],
          commitment_count: 3,
        }),
        planBudget(),
      ],
    },
    spent_outside_budgets: '1700.00',
    not_planned: '1490.01',
    outside_vs_not_planned: '209.99',
    ...over,
  }
}
