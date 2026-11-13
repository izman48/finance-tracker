import type { PlanBudget, PlanCommitmentItem, PlanResponse } from './plan'

/** GET /plan shaped like the T-25-2 contract. Synthetic names and amounts;
 *  the lines add up: 3,750.00 − 1,419.49 − 620.50 = 1,710.01 (Eating out
 *  counts at £370.50: £330.50 spent + £40.00 coming up, over its £300 limit). */
export function planBudget(over: Partial<PlanBudget> = {}): PlanBudget {
  return {
    budget_id: 'pb2', category: 'Groceries', limit: '250.00', spent: '120.00', coming_up: '0.00', planned: '250.00',
    status: 'under_pace', over_by: '0.00', commitments: [], other_purchases: '120.00', ...over,
  }
}

const item = (label: string, date: string, amount: string, status: PlanCommitmentItem['status']): PlanCommitmentItem =>
  ({ commitment_id: `c-${label}`, label, date, amount, status, transaction_id: status === 'paid' ? `tx-${label}` : null })

export function planResponse(over: Partial<PlanResponse> = {}): PlanResponse {
  return {
    cycle: { start: '2026-10-30', end: '2026-11-29', days_left: 16 },
    money_in: {
      total: '3750.00',
      items: [
        { label: 'Salary', date: '2026-10-30', amount: '2800.00', status: 'received', transaction_id: 'tx-sal' },
        { label: 'Lodger rent', date: '2026-11-01', amount: '600.00', status: 'received', transaction_id: 'tx-lodger' },
        { label: 'GIFT FROM GRAN', date: '2026-11-08', amount: '50.00', status: 'received', transaction_id: 'tx-gift' },
        { label: 'Side job', date: '2026-11-28', amount: '300.00', status: 'expected', transaction_id: null },
      ],
    },
    commitments: {
      total: '1419.49',
      groups: [
        { name: 'Rent & bills', total: '1305.00', count: 3, paid_count: 1, items: [
          item('Rent', '2026-11-01', '1200.00', 'paid'),
          item('Energy co', '2026-11-10', '85.00', 'not_seen'),
          item('Phone', '2026-11-16', '20.00', 'coming'),
        ] },
        { name: 'Subscriptions', total: '14.49', count: 2, paid_count: 1, items: [
          item('Streamly', '2026-11-04', '9.99', 'paid'),
          item('Cloudbox', '2026-11-21', '4.50', 'coming'),
        ] },
        { name: 'Savings', total: '100.00', count: 1, paid_count: 0, items: [item('ISA', '2026-11-20', '100.00', 'coming')] },
      ],
    },
    budgets: {
      limits_total: '550.00', planned_total: '620.50',
      items: [
        planBudget({
          budget_id: 'pb1', category: 'Eating out', limit: '300.00', spent: '330.50', coming_up: '40.00',
          planned: '370.50', status: 'over', over_by: '30.50', other_purchases: '310.50',
          commitments: [
            { commitment_id: 'c-pz', label: 'Pizza club', date: '2026-11-06', amount: '20.00', status: 'paid', transaction_id: 'tx-pz1' },
            { commitment_id: 'c-pz', label: 'Pizza club', date: '2026-11-20', amount: '20.00', status: 'due', transaction_id: null },
            { commitment_id: 'c-pz', label: 'Pizza club', date: '2026-11-27', amount: '20.00', status: 'due', transaction_id: null },
          ],
        }),
        planBudget(),
      ],
    },
    left_over: '1710.01',
    ...over,
  }
}
