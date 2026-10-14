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
