import { Asset } from '../services/api'

export const ASSET_TYPE_LABEL: Record<string, string> = {
  isa: 'ISA',
  savings: 'Savings',
  investment: 'Investments',
  pension: 'Pension',
  property: 'Property',
  crypto: 'Crypto',
  other: 'Other',
  mortgage: 'Mortgage',
  loan: 'Loan',
  other_liability: 'Other liability',
}

/** Types the user owes on — stored with a negative valuation (amount owed). */
export const LIABILITY_TYPES = new Set(['mortgage', 'loan', 'other_liability'])
export const isLiabilityType = (t: string) => LIABILITY_TYPES.has(t)

export const ASSET_TYPES = ['isa', 'savings', 'investment', 'pension', 'property', 'crypto', 'other']

/** Valuations are ordered oldest→newest; the last one is the current value
 *  (signed — negative for liabilities). */
export const latestValue = (a: Asset) =>
  a.valuations.length ? Number(a.valuations[a.valuations.length - 1].value) : 0
