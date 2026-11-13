import { describe, expect, it } from 'vitest'
import { budgetIncludes, subscriptionsWithoutBudget } from './plan'
import { planResponse } from './plan.fixtures'

// T-25-3: what the Budgets tab reads from GET /plan.
describe('budgetIncludes', () => {
  it("names each commitment a budget's spend includes, its paid payments summed", () => {
    const plan = planResponse()
    plan.budgets.items[0].commitments.push(
      { commitment_id: 'c-pz', label: 'Pizza club', date: '2026-11-13', amount: '20.50', status: 'paid', transaction_id: 'tx-pz2' },
      { commitment_id: 'c-kit', label: 'Meal kit', date: '2026-11-02', amount: '9.00', status: 'paid', transaction_id: 'tx-kit' },
    )
    expect(budgetIncludes(plan, 'Eating out')).toBe('Includes Pizza club £40.50, Meal kit £9.00')
  })

  it('nothing when no commitment was paid in it, or the budget is not in the plan', () => {
    const plan = planResponse()
    plan.budgets.items[0].commitments = plan.budgets.items[0].commitments.filter((c) => c.status === 'due')
    expect(budgetIncludes(plan, 'Eating out')).toBeNull()
    expect(budgetIncludes(plan, 'Groceries')).toBeNull()
    expect(budgetIncludes(null, 'Groceries')).toBeNull()
  })
})

describe('subscriptionsWithoutBudget', () => {
  const plan = planResponse()

  it("is the plan's Subscriptions group when no budget is for Subscriptions", () => {
    expect(subscriptionsWithoutBudget(plan, ['Groceries'])?.items.map((i) => i.label)).toEqual(['Streamly', 'Cloudbox'])
  })

  it('is nothing when a budget (paused or not, any case) covers Subscriptions, or there are none', () => {
    expect(subscriptionsWithoutBudget(plan, ['subscriptions'])).toBeNull()
    const none = planResponse()
    none.commitments.groups = none.commitments.groups.filter((g) => g.name !== 'Subscriptions')
    expect(subscriptionsWithoutBudget(none, [])).toBeNull()
    expect(subscriptionsWithoutBudget(null, [])).toBeNull()
  })
})
