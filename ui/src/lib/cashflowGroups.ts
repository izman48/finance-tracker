/** Cashflow's account list in three families (ux T-10-13; T-10-14b):
 *  Current accounts, Savings, Credit cards, always in that order. A card's
 *  figure always carries a word ("owed" / "in credit"), so debt isn't shown
 *  by colour alone. */
import { money } from './format'
import type { SummaryAccount } from '../types'

export interface Figure {
  text: string
  tone: string
}

export interface AccountGroup {
  key: 'current' | 'savings' | 'credit'
  heading: string
  accounts: SummaryAccount[]
  subtotal: Figure
}

/** A card's figure: "£6,000.00 owed", or "£50.00 in credit" for an overpaid card. */
export function cardFigure(owed: number | string | null | undefined): Figure {
  const n = Number(owed ?? 0)
  if (n < 0) return { text: `${money(-n)} in credit`, tone: 'text-pos' }
  return { text: `${money(n)} owed`, tone: 'text-warn' }
}

const balance = (accounts: SummaryAccount[]): Figure => ({
  text: money(accounts.reduce((sum, a) => sum + Number(a.current_balance ?? 0), 0)),
  tone: 'text-slate-100',
})

/** The groups that have accounts, in the fixed order. The cards' subtotal is
 *  the API's `credit_owed` (cards in credit don't offset it). */
export function cashflowGroups(accounts: SummaryAccount[], creditOwed: number | string): AccountGroup[] {
  const of = (role: string) => accounts.filter((a) => a.role === role)
  const current = of('spending')
  const savings = of('savings')
  const cards = of('credit')
  const groups: AccountGroup[] = [
    { key: 'current', heading: 'Current accounts', accounts: current, subtotal: balance(current) },
    { key: 'savings', heading: 'Savings', accounts: savings, subtotal: balance(savings) },
    { key: 'credit', heading: 'Credit cards', accounts: cards, subtotal: cardFigure(creditOwed) },
  ]
  return groups.filter((g) => g.accounts.length > 0)
}

/** The hero's line under Total cash: current and savings accounts only. */
export function heroSubline(cashAccounts: number): string {
  if (cashAccounts === 0) return 'no current or savings accounts connected'
  return `across ${cashAccounts} account${cashAccounts === 1 ? '' : 's'}`
}
