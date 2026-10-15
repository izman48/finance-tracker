/** Cashflow's accounts, in three headed families (ux T-10-13; T-10-14b). */
import { Link } from 'react-router-dom'
import { money } from '../../lib/format'
import { cardFigure, cashflowGroups } from '../../lib/cashflowGroups'
import { cardStatementLine } from '../../lib/cardStatement'
import { cardSettingsPath, repaymentNotSetUp } from '../../lib/credit'
import { RepaymentNotSetUpLine } from '../card/RepaymentNotSetUp'
import type { SummaryAccount } from '../../types'

export default function AccountGroups({ accounts, creditOwed }: { accounts: SummaryAccount[]; creditOwed: number | string }) {
  return (
    <div className="mt-6 space-y-5">
      {cashflowGroups(accounts, creditOwed).map((group) => (
        <section key={group.key} aria-labelledby={`accounts-${group.key}`}>
          <div className="flex items-baseline justify-between gap-3 pb-1 border-b border-white/[0.06]">
            <h3 id={`accounts-${group.key}`} className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              {group.heading}
            </h3>
            <span className={`text-sm font-semibold tnum shrink-0 ${group.subtotal.tone}`}>{group.subtotal.text}</span>
          </div>
          <div className="-mx-2 divide-y divide-white/[0.06]">
            {group.accounts.map((a) => (a.role === 'credit' ? <CardRow key={a.id} account={a} /> : <BalanceRow key={a.id} account={a} />))}
          </div>
        </section>
      ))}
    </div>
  )
}

function BalanceRow({ account }: { account: SummaryAccount }) {
  return (
    <div className="flex items-center justify-between gap-3 px-2 py-2.5">
      <div className="min-w-0">
        <div className="text-sm text-slate-200 truncate">{account.display_name}</div>
        <div className="text-xs text-slate-400 truncate">{account.provider_name}</div>
      </div>
      <div className="font-semibold tnum shrink-0 text-slate-100">{money(Number(account.current_balance ?? 0))}</div>
    </div>
  )
}

function CardRow({ account }: { account: SummaryAccount }) {
  const figure = cardFigure(account.credit_owed)
  return (
    <div className="px-2 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm text-slate-200 truncate">{account.display_name}</div>
          <StatementLine account={account} />
        </div>
        <div className={`font-semibold tnum shrink-0 ${figure.tone}`}>{figure.text}</div>
      </div>
      {repaymentNotSetUp(account) && <RepaymentNotSetUpLine account={account} />}
    </div>
  )
}

/** Line 2 of a card row: the statement, or the provider when the response
 *  has no statement data. Add statement / Add new are their own links. */
function StatementLine({ account }: { account: SummaryAccount }) {
  const line = cardStatementLine(account.statement)
  if (!line.text && !line.action) {
    return <div className="text-xs text-slate-400 truncate">{account.provider_name}</div>
  }
  return (
    <div className="text-xs text-slate-400 flex flex-wrap items-center gap-x-2">
      {line.text && <span>{line.text}</span>}
      {line.chip && <span className="chip-pos">{line.chip}</span>}
      {line.action && (
        <Link
          to={cardSettingsPath(account.id)}
          className={`inline-flex items-center min-h-[44px] ${line.action === 'Add new' ? 'chip-warn' : 'text-accent hover:underline'}`}
        >
          {line.action}
        </Link>
      )}
    </div>
  )
}
