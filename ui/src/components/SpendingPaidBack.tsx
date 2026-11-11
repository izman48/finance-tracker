import { gbp, gbp0 } from '../lib/format'
import type { Transaction } from '../types'

/** What friends' marked repayments took off this purchase (T-03-6), or 0. */
const paidBack = (t: Transaction) => (t.transaction_type === 'debit' ? Number(t.paid_back_amount ?? 0) : 0)

/** The chip on a Spending row: "£110 paid back" (PRD Screens 4). Text, not colour alone. */
export function PaidBackChip({ transaction }: { transaction: Transaction }) {
  const n = paidBack(transaction)
  return n > 0 ? <span className="chip-info">{gbp0(n)} paid back</span> : null
}

/** Under a Spending row: "£110.00 of £200.00 paid back. Counts as £90.00." (AC-32). The raw debit stays in the ledger. */
export function PaidBackLine({ transaction }: { transaction: Transaction }) {
  const n = paidBack(transaction)
  if (n <= 0) return null
  const amount = Math.abs(Number(transaction.amount))
  return (
    <div className="text-xs text-slate-400 mt-0.5">
      {gbp(n)} of {gbp(amount)} paid back. Counts as {gbp(amount - n)}.
    </div>
  )
}

/** A category's reference line for marks made against the category (no purchase): "Paid back by others −£110.00". */
export function CategoryPaidBack({ amount }: { amount: number | string | undefined }) {
  const n = Number(amount ?? 0)
  return n > 0 ? <div className="text-xs text-slate-400 mt-1">Paid back by others −{gbp(n)}</div> : null
}
