/** Shared money/date formatting. One definition each — don't re-declare per file. */

const GBP = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' })
const GBP0 = new Intl.NumberFormat('en-GB', {
  style: 'currency',
  currency: 'GBP',
  maximumFractionDigits: 0,
})

/** £1,234.56 — pennies included (lists, exact figures). */
export const gbp = (n: number) => GBP.format(n)

/** £1,235 — whole pounds (headlines, chart axes). */
export const gbp0 = (n: number) => GBP0.format(n)

/** Any-currency, null-tolerant variant for optional balances. */
export function money(amount: number | null | undefined, currency = 'GBP') {
  if (amount === null || amount === undefined) return 'N/A'
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency }).format(amount)
}

/** "1 Jul" */
export function dateDayMonth(date: string | null | undefined) {
  if (!date) return '—'
  return new Date(date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

/** "1 Jul 2026" */
export function dateLong(date: string | null | undefined) {
  if (!date) return '—'
  return new Date(date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** "01 Jul 2026" — 2-digit day (transaction tables). */
export function dateDMY(date: string | null | undefined) {
  if (!date) return '—'
  return new Date(date).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

/** "Jul 26" from a "YYYY-MM" key. */
export function monthLabel(ym: string) {
  const [y, m] = ym.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString('en-GB', { month: 'short', year: '2-digit' })
}

/** "just now" / "5m ago" / "3h ago" / "2d ago" */
export function timeAgo(iso: string | null) {
  if (!iso) return null
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}
