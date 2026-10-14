/** P2 on Cashflow (owner 2026-10-15; ux P-10..P-12): a bill linked to a
 *  loan, finance or BNPL debt reads "{lender} loan payment", by the one rule
 *  Home uses (`homeOwed.loanPaymentLabel`). Built in the UI from the API's
 *  liability fields (sec: not in the API, where Claude's tools would read
 *  it). The lender is user text and is only ever rendered as text. */
import { loanLenders, loanPaymentLabel } from './homeOwed'
import type { Upcoming } from './upcoming'
import type { Commitment } from '../types'

type LinkedLiability = Parameters<typeof loanLenders>[0][number]

/** Coming-up rows with each linked loan bill renamed; nothing else changes. */
export function withLoanLabels(rows: Upcoming[], lenders: Map<string, string>): Upcoming[] {
  return rows.map((u) => {
    const lender = !u.income && u.commitmentId ? lenders.get(u.commitmentId) : undefined
    return lender ? { ...u, label: loanPaymentLabel(lender) } : u
  })
}

/** Forecast events carry only a label, so {bill label: lender}, kept only
 *  where no other commitment has the same label (never rename the wrong bill). */
export function forecastLenders(liabilities: LinkedLiability[], commitments: Commitment[]): Map<string, string> {
  const uses = new Map<string, number>()
  for (const c of commitments) uses.set(c.label, (uses.get(c.label) ?? 0) + 1)
  const lenders = loanLenders(liabilities)
  return new Map(
    commitments.flatMap((c) =>
      lenders.has(c.id) && uses.get(c.label) === 1 ? [[c.label, lenders.get(c.id)!] as [string, string]] : [],
    ),
  )
}
