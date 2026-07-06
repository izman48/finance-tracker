import { Asset } from '../services/api'

export const ASSET_TYPE_LABEL: Record<string, string> = {
  isa: 'ISA',
  savings: 'Savings',
  investment: 'Investments',
  pension: 'Pension',
  property: 'Property',
  crypto: 'Crypto',
  other: 'Other',
}

/** Valuations are ordered oldest→newest; the last one is the current value. */
export const latestValue = (a: Asset) =>
  a.valuations.length ? Number(a.valuations[a.valuations.length - 1].value) : 0
