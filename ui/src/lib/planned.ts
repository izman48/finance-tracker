/** Planned-item money math, shared by the Commitments list and the add modal.
 *
 * Mirrors backend analytics/planned.py: installment_amount() splits a total
 * evenly, adding the fee up front and simple interest over the plan term.
 * Keep the two in step — the forecast uses the backend's figure, so a drift
 * here shows up as the UI and the chart disagreeing.
 */
import { monthlyEquivalent } from './cadence'

/** Per-installment payment: even split + optional fee and simple interest.
 *  Rounded to pence to match the backend's quantize, so the figure shown here
 *  and the one the forecast applies are the same number. Returns 0 rather than
 *  the whole total for a non-positive count — the add form calls this on every
 *  keystroke, including while the payments field is empty. */
export function perInstallment(total: number, n: number, apr: number, fee: number) {
  if (!n || n < 1) return 0
  let base = total
  if (fee) base += fee
  if (apr) base += total * (apr / 100) * (n / 12)
  return Math.round((base / n) * 100) / 100
}

interface PlannedLike {
  kind: string
  amount: number | string | null
  total_amount: number | string | null
  installments: number | null
  apr?: number | string | null
  fee_amount?: number | string | null
  cadence?: string | null
  interval_days?: number | null
  interval_months?: number | null
}

/** What actually leaves the account on each occurrence. (Money fields arrive
 *  from the API as strings — coerce before arithmetic.) */
export function plannedPerPayment(it: PlannedLike): number {
  if (it.kind === 'installment_plan') {
    return perInstallment(
      Number(it.total_amount) || 0,
      Number(it.installments) || 1,
      Number(it.apr) || 0,
      Number(it.fee_amount) || 0,
    )
  }
  return Number(it.amount) || 0
}

/** £/month, so a plan can be ranked and totalled beside recurring commitments. */
export function plannedMonthly(it: PlannedLike): number {
  return monthlyEquivalent({
    cadence: it.cadence || 'monthly',
    interval_days: it.interval_days,
    interval_months: it.interval_months,
    amount: plannedPerPayment(it),
  })
}

/** Plans and manual recurring items are money out on a schedule, so they belong
 *  in the regular income/expense lists. A one-off isn't regular — it stays in
 *  its own section. */
export const isRegularPlanned = (it: PlannedLike) =>
  it.kind === 'installment_plan' || it.kind === 'recurring'
