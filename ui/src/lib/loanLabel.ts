/** P2 on Cashflow (owner 2026-10-15; ux P-10..P-12): a bill linked to a
 *  loan, finance or BNPL debt reads "{lender} loan payment", by the one rule
 *  Home uses (`homeOwed.loanPaymentLabel`). Built in the UI from the API's
 *  liability fields (sec: not in the API, where Claude's tools would read
 *  it). The lender is user text and is only ever rendered as text. */
import { loanPaymentLabel } from './homeOwed'
import type { Upcoming } from './upcoming'

/** Coming-up rows with each linked loan bill renamed; nothing else changes. */
export function withLoanLabels(rows: Upcoming[], lenders: Map<string, string>): Upcoming[] {
  return rows.map((u) => {
    const lender = !u.income && u.commitmentId ? lenders.get(u.commitmentId) : undefined
    return lender ? { ...u, label: loanPaymentLabel(lender) } : u
  })
}
