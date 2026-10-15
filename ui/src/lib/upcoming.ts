/** "Coming up": every next dated movement the forecast applies, merged from
 *  the three sources of future money (confirmed commitments, scheduled card
 *  repayments, planned items) and sorted by date. Shared by Home and Cashflow
 *  so the two never disagree about what's next. */
import { Commitment, NextRepayment, PlannedItem } from '../types'
import { daysLate, moneyStyle } from './late'
import { nextPlannedDate, plannedPerPayment } from './planned'
import { cardBillLabel, type BillPart } from './cardBill'

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
  /** An unpaid planned expense past its date (API-decided): still counts. */
  overdue?: { due: string; days: number }
  /** An unpaid one-off expense just past its date, inside the API's grace (O9): a normal row, still counted. */
  justDue?: { due: string }
  /** A credit card's repayment: "{card} bill", or "{card} bill (projected)" (T-10-14d, T-12-7a). */
  cardBill?: boolean
  /** What the card bill is made of, from the API; Cashflow's line 2. */
  billParts?: BillPart[]
}

/** How a row's amount reads: late income is not money you have, so no "+" and no green. */
export function upcomingAmount(u: Upcoming): { sign: string; tone: string } {
  return moneyStyle(u.income, Boolean(u.late))
}

/** A late, overdue or just-due row's date is in its own line; don't repeat it beside the amount. */
export function upcomingShowsDate(u: Upcoming): boolean {
  return !u.late && !u.overdue && !u.justDue
}

export function buildUpcoming(
  commitments: Commitment[],
  repayments: NextRepayment[],
  planned: PlannedItem[],
  today: string,
  limit = 4,
): Upcoming[] {
  // Late income first, most overdue first (ux spec 3): shown, never counted.
  const lateIncome: Upcoming[] = [
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

  // Unpaid planned expenses past their date (ux spec 3a): they still count.
  const overdue: Upcoming[] = planned
    .filter((p) => p.overdue && p.direction !== 'income' && !p.matched_transaction_id)
    .map((p) => ({
      key: `overdue-p-${p.id}`, label: p.name, amount: plannedPerPayment(p), date: p.start_date,
      income: false, claudeAuditId: p.changed_by_claude?.audit_id,
      overdue: { due: p.start_date, days: daysLate(p.start_date, today) },
    }))

  // Unpaid one-off expenses just past their date, before the API calls them
  // overdue (O9): a normal row that still counts, with a "Due {date}" line.
  const justDue: Upcoming[] = planned
    .filter((p) => isJustDue(p, today))
    .map((p) => ({
      key: `due-p-${p.id}`, label: p.name, amount: plannedPerPayment(p), date: p.start_date,
      income: false, claudeAuditId: p.changed_by_claude?.audit_id, justDue: { due: p.start_date },
    }))

  const pastDue = [...lateIncome, ...overdue, ...justDue].sort((a, b) => a.date.localeCompare(b.date))

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
      label: cardBillLabel(r.label, Boolean(r.projected)),
      amount: Number(r.amount),
      date: r.due_date,
      income: false,
      cardBill: true,
      billParts: r.parts,
    })),
    // A planned item its real transaction already paid is no longer coming (T-08-7).
    ...planned.filter((p) => !p.matched_transaction_id && !p.late && !(p.overdue && p.direction !== 'income') && !isJustDue(p, today)).flatMap((p) => {
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

  return [...pastDue, ...future].slice(0, limit)
}

function isJustDue(p: PlannedItem, today: string): boolean {
  return p.kind === 'one_off' && p.direction !== 'income' && !p.overdue && !p.matched_transaction_id
    && p.start_date < today
}
