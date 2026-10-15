/** How a card bill reads (T-12-7a part 2; ux T-12-1 "Projected bill", lead
 *  decision 2026-10-15). The API says whether a repayment is projected and
 *  what it is made of (`parts`, summed to the amount); the browser only
 *  words it and never adds anything up. */
import { gbp } from './format'

export interface BillPart {
  kind: 'statement' | 'spent_since' | 'balance'
  amount: number | string
}

export function cardBillLabel(card: string, projected: boolean): string {
  return `${card} bill${projected ? ' (projected)' : ''}`
}

const ORDER: BillPart['kind'][] = ['statement', 'spent_since', 'balance']
const WORDS: Record<BillPart['kind'], string> = {
  statement: 'still due',
  spent_since: 'spent since',
  balance: 'balance',
}

/** Cashflow's line 2 under a card bill: `Spent since £140.00`, `Balance
 *  £640.30`, or `Still due £500.00 + spent since £140.00`. A real statement
 *  on its own needs none (its amount is the statement). Parts at 0 are left
 *  out. */
export function billPartsLine(parts: BillPart[] | undefined): string | null {
  const shown = (parts ?? [])
    .filter((p) => Number(p.amount) > 0)
    .sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind))
  if (shown.length === 0 || (shown.length === 1 && shown[0].kind === 'statement')) return null
  const line = shown.map((p) => `${WORDS[p.kind]} ${gbp(Number(p.amount))}`).join(' + ')
  return line.charAt(0).toUpperCase() + line.slice(1)
}
