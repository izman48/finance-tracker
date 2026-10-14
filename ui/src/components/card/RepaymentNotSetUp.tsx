/** The D8 notice (owner, T-10-12): a card that owes money with no repayment
 *  set up is left out of the forecast. Shown where card debt shows, with a
 *  link that opens the card's settings on Wealth. */
import { Link } from 'react-router-dom'
import { ChevronRight, CircleAlert } from 'lucide-react'
import { cardSettingsPath, REPAYMENT_NOT_SET_UP } from '../../lib/credit'
import type { SummaryAccount } from '../../types'

/** Under the card's row in the Cashflow account list. */
export function RepaymentNotSetUpLine({ account }: { account: SummaryAccount }) {
  return (
    <p className="text-xs text-warn mt-0.5">
      {REPAYMENT_NOT_SET_UP}.{' '}
      <Link to={cardSettingsPath(account.id)} className="inline-flex items-center min-h-[44px] underline hover:text-accent">
        Set up repayment
      </Link>
    </p>
  )
}

/** Home: the summary cards are links already, so this is its own row. */
export function RepaymentNotSetUpBanner({ account }: { account: SummaryAccount }) {
  return (
    <Link
      to={cardSettingsPath(account.id)}
      className="mb-6 flex items-center justify-between gap-3 card px-4 py-3 hover:border-accent/25 transition-colors"
    >
      <span className="flex items-center gap-2 text-sm text-slate-200 min-w-0">
        <CircleAlert className="w-4 h-4 text-warn shrink-0" />
        <span>
          <span className="font-semibold">{account.display_name}</span>: {REPAYMENT_NOT_SET_UP}. Set up repayment
        </span>
      </span>
      <ChevronRight className="w-4 h-4 text-slate-500 shrink-0" />
    </Link>
  )
}
