/** Home's two debt touches (ux T-10-13 H1, H2; T-10-14d). Home summarises;
 *  every figure is the API's and the breakdown lives on Wealth. */
import type { Upcoming } from './upcoming'

/** The Wealth card's debt row: "Total owed" from the API's `total_owed`
 *  (cards plus loans, summed by the server), shown only above £0. Before the
 *  API sends it, the row stays as it was ("Owed on credit"), so the browser
 *  never adds debts up itself. */
export function owedRow(summary: {
  total_owed?: number | string | null
  credit_owed: number | string
}): { label: string; amount: number } | null {
  if (summary.total_owed === undefined || summary.total_owed === null) {
    return { label: 'Owed on credit', amount: Number(summary.credit_owed) }
  }
  const total = Number(summary.total_owed)
  return total > 0 ? { label: 'Total owed', amount: total } : null
}

/** How a coming-up row reads on Home: a card repayment is "{card} bill";
 *  a loan's linked repayment is "{lender} loan payment", or "{lender} payment"
 *  when the lender already says "loan" (owner P2, ux). */
export function homeUpcomingLabel(u: Upcoming, lenders: Map<string, string> = new Map()): string {
  if (u.cardBill) return `${u.label} bill`
  const lender = u.commitmentId ? lenders.get(u.commitmentId) : undefined
  return lender ? loanPaymentLabel(lender) : u.label
}

/** A loan's linked repayment: "{lender} loan payment", or "{lender} payment"
 *  when the lender already says "loan", so it never reads "loan loan payment"
 *  (ux T-10-15a). Shared by Home and Cashflow so there is one rule. */
export function loanPaymentLabel(lender: string): string {
  return /loan/i.test(lender) ? `${lender} payment` : `${lender} loan payment`
}

/** {commitment id: lender} for each liability whose repayment is a linked bill. */
export function loanLenders(
  liabilities: { lender: string; linked_commitment: { id: string; label: string } | null }[],
): Map<string, string> {
  return new Map(
    liabilities.filter((l) => l.linked_commitment).map((l) => [l.linked_commitment!.id, l.lender] as [string, string]),
  )
}
