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

it('two commitments with the same label are named separately (eng-a on #309)', () => {
  const plan = planResponse()
  plan.budgets.items[0].commitments.push(
    { commitment_id: 'c-pz2', label: 'Pizza club', date: '2026-11-13', amount: '5.00', status: 'paid', transaction_id: 'tx-pz9' },
  )
  expect(budgetIncludes(plan, 'Eating out')).toBe('Includes Pizza club £20.00, Pizza club £5.00')
})

describe('subscriptionsWithoutBudget', () => {
  it('matches the budget category exactly, as the API does (eng-a on #309)', () => {
    // A "subscriptions" budget does not take the "Subscriptions" category, so Plan still lists them.
    expect(subscriptionsWithoutBudget(planResponse(), ['subscriptions'])).not.toBeNull()
  })

  const plan = planResponse()

  it("is the plan's Subscriptions group when no budget is for Subscriptions", () => {
    expect(subscriptionsWithoutBudget(plan, ['Groceries'])?.items.map((i) => i.label)).toEqual(['Streamly', 'Cloudbox'])
  })

  it('is nothing when a budget (paused or not) is for Subscriptions, or there are none', () => {
    expect(subscriptionsWithoutBudget(plan, ['Subscriptions'])).toBeNull()
    const none = planResponse()
    none.commitments.groups = none.commitments.groups.filter((g) => g.name !== 'Subscriptions')
    expect(subscriptionsWithoutBudget(none, [])).toBeNull()
    expect(subscriptionsWithoutBudget(null, [])).toBeNull()
  })
})
