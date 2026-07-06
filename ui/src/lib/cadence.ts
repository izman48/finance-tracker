/** Commitment cadence display + math, shared by Plan surfaces and modals.
 *
 * Yearly is stored as every-12-months (`every_n_months`, interval_months >= 12);
 * these helpers own that encoding so pages don't re-implement it.
 */

interface CadenceLike {
  cadence: string
  interval_days?: number | null
  interval_months?: number | null
}

export const CADENCE_LABEL: Record<string, string> = {
  weekly: 'Weekly',
  monthly: 'Monthly',
  every_n_months: 'Every few months',
  custom_days: 'Custom',
}

export const isYearly = (c: CadenceLike) =>
  c.cadence === 'every_n_months' && Number(c.interval_months) >= 12

export const cadenceLabel = (c: CadenceLike) =>
  isYearly(c) ? 'Yearly' : CADENCE_LABEL[c.cadence] ?? c.cadence

/** Normalize an amount to £/month across cadences. (Amounts arrive as strings
 *  from the API — coerce before arithmetic.) */
export function monthlyEquivalent(c: CadenceLike & { amount: number | string }) {
  const amount = Number(c.amount) || 0
  if (c.cadence === 'weekly') return amount * (52 / 12)
  if (c.cadence === 'every_n_months') return amount / (c.interval_months || 1)
  if (c.cadence === 'custom_days') return amount * (30.44 / (c.interval_days || 30))
  return amount
}

/** match_key is stored as "<direction>:<merchant>" — show just the merchant. */
export const merchantFromKey = (key: string | null) =>
  key ? key.split(':').slice(1).join(':') : ''
