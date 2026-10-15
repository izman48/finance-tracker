import { describe, expect, it } from 'vitest'
import { accountOptionGroups } from './accountOptions'

// T-10-16: the Spending "All accounts" filter lists accounts in the same
// families, in the same order, as Wealth and Cashflow. Synthetic accounts.
const acc = (id: string, name = id) => ({ id, display_name: name })
const accounts = [acc('card', 'Test Card'), acc('sav', 'Saver'), acc('cur', 'Current'), acc('ex', 'Old joint'), acc('cur2', 'Second current')]
const roles = new Map([['card', 'credit'], ['sav', 'savings'], ['cur', 'spending'], ['ex', 'excluded'], ['cur2', 'spending']])

describe('accountOptionGroups', () => {
  it('groups Current accounts, Savings, Credit cards in that order', () => {
    const groups = accountOptionGroups(accounts, roles)
    expect(groups.map((g) => g.label)).toEqual(['Current accounts', 'Savings', 'Credit cards'])
    expect(groups[0].accounts.map((a) => a.id)).toEqual(['cur', 'cur2'])
    expect(groups[1].accounts.map((a) => a.id)).toEqual(['sav'])
    expect(groups[2].accounts.map((a) => a.id)).toEqual(['card'])
  })

  it('leaves excluded accounts out', () => {
    const ids = accountOptionGroups(accounts, roles).flatMap((g) => g.accounts.map((a) => a.id))
    expect(ids).not.toContain('ex')
  })

  it('drops an empty group', () => {
    const groups = accountOptionGroups([acc('cur')], roles)
    expect(groups.map((g) => g.label)).toEqual(['Current accounts'])
  })

  it('without roles (summary not loaded), one unlabelled list keeps every account usable', () => {
    expect(accountOptionGroups(accounts, null)).toEqual([{ label: null, accounts }])
  })

  it('an account the summary does not know stays listed, after the groups', () => {
    const groups = accountOptionGroups([...accounts, acc('new', 'New account')], roles)
    expect(groups[groups.length - 1]).toEqual({ label: 'Other', accounts: [acc('new', 'New account')] })
  })

  it('an unknown role is listed under Other, never dropped', () => {
    const groups = accountOptionGroups([acc('odd')], new Map([['odd', 'pension']]))
    expect(groups).toEqual([{ label: 'Other', accounts: [acc('odd')] }])
  })
})
