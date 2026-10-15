import type { SummaryAccount } from '../../types'
import { gbp0 } from '../../lib/format'
import { cardStatementLine } from '../../lib/cardStatement'
import { cardPlanChips, wealthPlanLine } from '../../lib/cardPlans'
import type { CardPlan } from '../../services/api'

/** A credit card on the Wealth balance sheet (ux T-10-13). Line 2 holds the
 *  statement; the figure is debt with the word "owed" for screen readers, or
 *  "in credit". The row opens card settings; `Add statement` / `Add new` are
 *  separate buttons after it, never nested inside it. Its instalment plans
 *  (T-12-7b) are a labelled list under it: text only, never in a total. */
export default function CardRow({ account, plans = [], onOpen }: {
  account: SummaryAccount
  plans?: CardPlan[]
  onOpen: () => void
}) {
  const planChips = cardPlanChips(plans)
  const owed = Number(account.credit_owed ?? 0)
  const line = cardStatementLine(account.statement)
  const detail = line.text
    ? line.withProvider ? `${account.provider_name} · ${line.text}` : line.text
    : account.provider_name
  const rowClass =
    'w-full min-h-[44px] flex items-center gap-3 px-4 py-3 text-left hover:bg-white/[0.03] transition-colors ' +
    'focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent'
  return (
    <div className="border-t border-white/[0.06]">
      <button type="button" onClick={onOpen} className={rowClass}>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-slate-100 truncate">{account.display_name}</span>
          <span className="block text-xs text-slate-400">
            {detail}
            {planChips.includes && ` · ${planChips.includes}`}
            {line.chip && <span className="chip-pos ml-2">{line.chip}</span>}
            {planChips.unconfirmed && <span className="chip-warn ml-2">{planChips.unconfirmed}</span>}
          </span>
        </span>
        <span className="chip shrink-0">live</span>
        {owed > 0 ? (
          <span className="shrink-0 text-sm font-semibold tnum text-warn">
            −{gbp0(owed)}<span className="sr-only"> owed</span>
          </span>
        ) : (
          <span className="shrink-0 text-sm font-semibold tnum text-slate-100">
            {gbp0(Math.abs(owed))}{owed < 0 ? ' in credit' : ''}
          </span>
        )}
      </button>
      {line.action && (
        <button
          type="button"
          onClick={onOpen}
          className={`${line.action === 'Add new' ? 'chip-warn' : 'text-xs text-accent underline'} ml-4 mb-3 min-h-[44px] sm:min-h-0`}
        >
          {line.action}
        </button>
      )}
      {plans.length > 0 && (
        <ul aria-label={`Plans on ${account.display_name}`} className="pl-8 pr-4 pb-3 space-y-2">
          {plans.map((p) => <PlanRow key={p.id} plan={p} provider={account.provider_name} />)}
        </ul>
      )}
    </div>
  )
}

/** One plan under its card (ux T-12-1): unconfirmed shows what is left, no
 *  minus sign; confirmed is already in the card balance. Neither is added. */
function PlanRow({ plan, provider }: { plan: CardPlan; provider: string }) {
  return (
    <li className="flex items-start gap-3">
      <span className="min-w-0 flex-1">
        <span className="block text-sm text-slate-200">
          {plan.name}
          {!plan.provider_confirmed && <span className="chip-warn ml-2">Not in net worth yet</span>}
        </span>
        <span className="block text-xs text-slate-400">{wealthPlanLine(plan, provider)}</span>
      </span>
      {plan.provider_confirmed ? (
        <span className="shrink-0 text-right text-sm tnum text-slate-400">
          −{gbp0(Number(plan.balance))}
          <span className="block text-xs">already counted</span>
        </span>
      ) : (
        <span className="shrink-0 text-sm tnum text-slate-400">{gbp0(Number(plan.balance))} left</span>
      )}
    </li>
  )
}
