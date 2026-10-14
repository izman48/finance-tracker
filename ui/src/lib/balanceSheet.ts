import { isLiabilityType } from './assets'
import { LOANS_GROUP_LABEL } from './liabilities'

/** The balance sheet's groups, in order (ux T-10-13): current accounts and
 *  credit cards are named the same way on every page, and everything owed
 *  (credit cards, then loans and finance) sits together. */
export const BALANCE_SHEET_GROUPS = [
  { key: 'cash', label: 'Current accounts' },
  { key: 'savings', label: 'Savings' },
  { key: 'invest', label: 'Investments & pensions' },
  { key: 'property', label: 'Property' },
  { key: 'other', label: 'Other' },
  { key: 'owed', label: 'Credit cards' },
  { key: 'liabilities', label: LOANS_GROUP_LABEL },
  { key: 'excluded', label: 'Excluded' },
] as const

type GroupKey = (typeof BALANCE_SHEET_GROUPS)[number]['key']

const ROLE_GROUP: Record<string, GroupKey> = {
  spending: 'cash',
  savings: 'savings',
  credit: 'owed',
  excluded: 'excluded',
}

const ASSET_GROUP: Record<string, GroupKey> = {
  savings: 'savings',
  isa: 'invest',
  investment: 'invest',
  pension: 'invest',
  crypto: 'invest',
  property: 'property',
  other: 'other',
}

/** A bank account's group: Credit cards is for credit-role accounts only. */
export function accountGroup(role: string): GroupKey {
  return ROLE_GROUP[role] ?? 'other'
}

/** A manual asset's group. Liability types, and any asset worth less than
 *  nothing (say, money owed to a friend), sit with loans and finance; a
 *  manual asset is never a credit card (ux on #192). */
export function assetGroup(assetType: string, value: number): GroupKey {
  if (isLiabilityType(assetType) || value < 0) return 'liabilities'
  return ASSET_GROUP[assetType] ?? 'other'
}
