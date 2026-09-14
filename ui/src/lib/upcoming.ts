/** "Coming up": every next dated movement the forecast applies, merged from
 *  the three sources of future money (confirmed commitments, scheduled card
 *  repayments, planned items) and sorted by date. Shared by Home and Cashflow
 *  so the two never disagree about what's next. */
import { Commitment, NextRepayment, PlannedItem } from '../types'
import { nextPlannedDate, plannedPerPayment } from './planned'

export interface Upcoming {
  key: string
  label: string
  amount: number
  date: string
  income: boolean
  commitmentId?: string
}

export function buildUpcoming(
  commitments: Commitment[],
  repayments: NextRepayment[],
  planned: PlannedItem[],
  today: string,
  limit = 4,
): Upcoming[] {
  return [
    ...commitments
      .filter((c) => c.status === 'confirmed' && c.next_date >= today)
      .map((c) => ({
        key: `c-${c.id}`,
        label: c.label,
        amount: Number(c.amount),
        date: c.next_date,
        income: c.direction === 'income',
        commitmentId: c.id,
      })),
    ...repayments.map((r) => ({
      key: `r-${r.account_id}-${r.due_date}`,
      label: r.label,
      amount: Number(r.amount),
      date: r.due_date,
      income: false,
    })),
    ...planned.flatMap((p) => {
      const date = nextPlannedDate(p, today)
      return date
        ? [{
            key: `p-${p.id}-${date}`,
            label: p.name,
            amount: plannedPerPayment(p),
            date,
            income: p.direction === 'income',
          }]
        : []
    }),
  ]
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, limit)
}
