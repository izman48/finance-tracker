import { accountGroup, BALANCE_SHEET_GROUPS } from './balanceSheet'

/** The families an account filter lists, in Wealth and Cashflow's order
 *  (T-10-16). Excluded accounts are left out. */
const LISTED = ['cash', 'savings', 'owed'] as const

export interface AccountOptionGroup<A> {
  label: string | null
  accounts: A[]
}

/** Accounts as <optgroup>s: Current accounts, Savings, Credit cards, by the
 *  role the summary resolved. Without roles, one unlabelled list so the
 *  filter still works; an account the summary doesn't know (or an unknown
 *  role) goes last. */
export function accountOptionGroups<A extends { id: string }>(
  accounts: A[],
  roles: Map<string, string> | null,
): AccountOptionGroup<A>[] {
  if (!roles) return [{ label: null, accounts }]
  const groups: AccountOptionGroup<A>[] = LISTED.map((key) => ({
    label: BALANCE_SHEET_GROUPS.find((g) => g.key === key)!.label,
    accounts: accounts.filter((a) => roles.has(a.id) && accountGroup(roles.get(a.id)!) === key),
  }))
  const listed = new Set<string>(LISTED)
  const other = accounts.filter((a) => {
    const role = roles.get(a.id)
    return role === undefined || (role !== 'excluded' && !listed.has(accountGroup(role)))
  })
  groups.push({ label: 'Other', accounts: other })
  return groups.filter((g) => g.accounts.length > 0)
}
