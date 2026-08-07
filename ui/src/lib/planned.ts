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

function localDate(iso: string) {
  return new Date(`${iso}T00:00:00`)
}

function isoDate(d: Date) {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Add months the way the backend's `_add_months` does: clamp to the last day
 *  of the target month rather than overflowing into the next one. `setMonth`
 *  would turn 31 Jan into 3 Mar, so a plan starting late in the month would
 *  preview dates the forecast never uses. */
function addMonths(d: Date, months: number) {
  const monthIndex = d.getMonth() + months
  const year = d.getFullYear() + Math.floor(monthIndex / 12)
  const month = ((monthIndex % 12) + 12) % 12
  const lastDay = new Date(year, month + 1, 0).getDate()
  return new Date(year, month, Math.min(d.getDate(), lastDay))
}

/** Match the backend cadence step for the small number of client-side previews. */
export function stepPlannedDate(
  iso: string,
  cadence: string | null | undefined,
  intervalDays?: number | null,
  intervalMonths?: number | null,
) {
  const d = localDate(iso)
  if (cadence === 'weekly') d.setDate(d.getDate() + 7)
  else if (cadence === 'every_n_months') return isoDate(addMonths(d, intervalMonths || 1))
  else if (cadence === 'custom_days') d.setDate(d.getDate() + (intervalDays || 30))
  else return isoDate(addMonths(d, 1))
  return isoDate(d)
}

/** The next date on which a planned item affects cashflow, or null when done. */
export function nextPlannedDate(it: PlannedLike & { start_date: string; end_date?: string | null }, today: string) {
  if (it.kind === 'one_off') return it.start_date >= today ? it.start_date : null
  let date = it.start_date
  // A plan runs for exactly its installments; a recurring item runs until its
  // end_date. Mirror planned_events(), which applies end_date only to the
  // recurring branch, so this list can't disagree with the forecast.
  const plan = it.kind === 'installment_plan'
  const count = plan ? Number(it.installments) || 0 : 600
  for (let i = 0; i < count; i += 1) {
    if (date >= today && (plan || !it.end_date || date <= it.end_date)) return date
    date = stepPlannedDate(date, it.cadence, it.interval_days, it.interval_months)
  }
  return null
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
