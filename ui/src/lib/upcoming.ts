/** "Coming up": every next dated movement the forecast applies, merged from
 *  the three sources of future money (confirmed commitments, scheduled card
 *  repayments, planned items) and sorted by date. Shared by Home and Cashflow
 *  so the two never disagree about what's next. */
import { Commitment, NextRepayment, PlannedItem } from '../types'
import { daysLate } from './late'
import { nextPlannedDate, plannedPerPayment } from './planned'

export interface Upcoming {
  key: string
  label: string
  amount: number
  date: string
  income: boolean
  commitmentId?: string
  /** Claude's latest change still in effect, for the "Changed by Claude" link. */
  claudeAuditId?: string
  /** Planned income: shown, but not counted until it arrives (D1). */
  plannedIncome?: boolean
  /** Income that hasn't arrived (T-08-10): `date` is when it was expected. */
  late?: { expected: string; days: number }
}

/** How a row's amount reads: late income is not money you have, so no "+" and no green. */
export function upcomingAmount(u: Upcoming): { sign: string; tone: string } {
  if (u.late) return { sign: '', tone: 'text-slate-400' }
  return u.income ? { sign: '+', tone: 'text-pos' } : { sign: '', tone: 'text-slate-100' }
}

export function buildUpcoming(
  commitments: Commitment[],
  repayments: NextRepayment[],
  planned: PlannedItem[],
  today: string,
  limit = 4,
): Upcoming[] {
  // Late income first, most overdue first (ux spec 3): shown, never counted.
  const late: Upcoming[] = [
    ...commitments
      .filter((c) => c.status === 'confirmed' && c.late && c.expected_date)
      .map((c) => ({
        key: `late-c-${c.id}`, label: c.label, amount: Number(c.amount), date: c.expected_date!,
        income: true, commitmentId: c.id, claudeAuditId: c.changed_by_claude?.audit_id,
      })),
    ...planned
      .filter((p) => p.late)
      .map((p) => ({
        key: `late-p-${p.id}`, label: p.name, amount: plannedPerPayment(p), date: p.start_date,
        income: true, plannedIncome: true, claudeAuditId: p.changed_by_claude?.audit_id,
      })),
  ]
    .map((u) => ({ ...u, late: { expected: u.date, days: daysLate(u.date, today) } }))
    .sort((a, b) => a.date.localeCompare(b.date))

  const future: Upcoming[] = [
    ...commitments
      .filter((c) => c.status === 'confirmed' && c.next_date >= today)
      .map((c) => ({
        key: `c-${c.id}`,
        label: c.label,
        amount: Number(c.amount),
        date: c.next_date,
        income: c.direction === 'income',
        commitmentId: c.id,
        claudeAuditId: c.changed_by_claude?.audit_id,
      })),
    ...repayments.map((r) => ({
      key: `r-${r.account_id}-${r.due_date}`,
      label: r.label,
      amount: Number(r.amount),
      date: r.due_date,
      income: false,
    })),
    // A planned item its real transaction already paid is no longer coming (T-08-7).
    ...planned.filter((p) => !p.matched_transaction_id && !p.late).flatMap((p) => {
      const date = nextPlannedDate(p, today)
      return date
        ? [{
            key: `p-${p.id}-${date}`,
            label: p.name,
            amount: plannedPerPayment(p),
            date,
            income: p.direction === 'income',
            plannedIncome: p.direction === 'income',
            claudeAuditId: p.changed_by_claude?.audit_id,
          }]
        : []
    }),
  ]
    .sort((a, b) => a.date.localeCompare(b.date))

  return [...late, ...future].slice(0, limit)
}
