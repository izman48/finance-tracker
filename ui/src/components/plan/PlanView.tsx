import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import {
  budgetLine, budgetsSubline, commitmentsSubline, cycleText, groupLabel, itemStatus, moneyInSubline, planMoney,
  type PlanResponse,
} from '../../lib/plan'

export interface PlanViewProps {
  status: 'loading' | 'error' | 'ready'
  data: PlanResponse | null
  onRetry: () => void
}

// The 2px accent focus ring `.btn` uses, offset inward so the card doesn't clip it (ux on #297).
const rowClass = 'w-full min-h-[44px] flex items-center gap-2 py-2 text-left text-sm rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent/60 focus-visible:-outline-offset-2'

/** One line of the plan. With children it is a disclosure button whose panel
 *  is always in the markup (so aria-controls points at something), hidden
 *  until opened. */
function Row({ label, sub, amount, children }: { label: string; sub?: ReactNode; amount?: string; children?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const body = (
    <>
      <span className="min-w-0 flex-1">
        <span className="text-slate-100">{label}</span>{' '}
        {sub && <span className="block text-xs text-slate-400">{sub}</span>}
      </span>
      {amount && <span className="shrink-0 tnum text-slate-100">{amount}</span>}
    </>
  )
  if (!children) return <div className={rowClass}><span className="w-4 shrink-0" />{body}</div>
  return (
    <div>
      <button type="button" className={rowClass} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((o) => !o)}>
        <ChevronRight aria-hidden className={`w-4 h-4 shrink-0 text-slate-500 transition-transform ${open ? 'rotate-90' : ''}`} />
        {body}
      </button>
      <div id={panelId} hidden={!open} className="pl-6 pb-2">{children}</div>
    </div>
  )
}

function Item({ label, status, amount }: { label: string; status: string; amount: string }) {
  const chip = status.startsWith('Paid') || status.startsWith('Received') ? 'chip-pos' : 'chip'
  return (
    <li className="flex items-center gap-2 py-1.5 text-sm">
      {/* Label and chip wrap together at 320px; the amount keeps its place. */}
      <span className="min-w-0 flex-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="min-w-0 break-words text-slate-300">{label}</span>{' '}
        <span className={chip}>{status}</span>
      </span>{' '}
      <span className="shrink-0 tnum text-slate-200">{amount}</span>
    </li>
  )
}

function Empty({ label, note, to, action }: { label: string; note: string; to: string; action: string }) {
  return (
    <div className={rowClass}>
      <span className="w-4 shrink-0" />
      <span className="min-w-0 flex-1">
        <span className="text-slate-100">{label}</span>{' '}
        <span className="block text-xs text-slate-400">{note}. <Link to={to} className="btn-link !text-xs">{action}</Link></span>
      </span>
    </div>
  )
}

function Lines({ data }: { data: PlanResponse }) {
  const { money_in: moneyIn, commitments, budgets } = data
  const hasMoneyIn = moneyIn.items.length > 0
  const leftOver = Number(data.left_over)
  return (
    <>
      <div className="divide-y divide-white/[0.06]">
        {hasMoneyIn ? (
          <Row label="Money in" sub={moneyInSubline(moneyIn)} amount={planMoney(moneyIn.total)}>
            <ul>{moneyIn.items.map((i, n) => <Item key={n} label={i.label} status={itemStatus(i.status, i.date)} amount={planMoney(i.amount)} />)}</ul>
          </Row>
        ) : (
          <Empty label="Money in" note="No money in found this cycle" to="/commitments" action="Check your income" />
        )}
        {commitments.groups.length > 0 ? (
          <Row label="Commitments" sub={commitmentsSubline(commitments)} amount={planMoney(commitments.total)}>
            {commitments.groups.map((g) => (
              <Row key={g.name} label={groupLabel(g)} sub={`${g.paid_count} of ${g.count} paid`} amount={planMoney(g.total)}>
                <ul>
                  {g.items.map((c, i) => <Item key={i} label={c.label} status={itemStatus(c.status, c.date)} amount={planMoney(c.amount)} />)}
                </ul>
              </Row>
            ))}
          </Row>
        ) : (
          <Empty label="Commitments" note="Nothing scheduled" to="/commitments" action="Add a commitment" />
        )}
        {budgets.items.length > 0 ? (
          <Row label="Budgets" sub={budgetsSubline(budgets)} amount={planMoney(budgets.planned_total)}>
            {budgets.items.map((b) => (
              <Row key={b.budget_id} label={b.category} sub={budgetLine(b)} amount={planMoney(b.planned)}>
                <ul>
                  {b.commitments.filter((c) => c.status === 'paid').map((c, i) => (
                    <Item key={`paid-${i}`} label={c.label} status={itemStatus(c.status, c.date)} amount={planMoney(c.amount)} />
                  ))}
                  {Number(b.other_purchases) > 0 && <Item label="Other purchases" status="Paid" amount={planMoney(b.other_purchases)} />}
                  {b.commitments.filter((c) => c.status === 'due').map((c, i) => (
                    <Item key={`due-${i}`} label={c.label} status={itemStatus(c.status, c.date)} amount={planMoney(c.amount)} />
                  ))}
                </ul>
              </Row>
            ))}
          </Row>
        ) : (
          <Empty label="Budgets" note="No budgets set" to="/insights?section=budgets" action="Suggest budgets" />
        )}
        {hasMoneyIn && <Row label="Left over" amount={planMoney(data.left_over)} />}
      </div>

      {hasMoneyIn && (
        <p className="mt-4 text-xs text-slate-400 tnum">
          {planMoney(moneyIn.total)} − {planMoney(commitments.total)} − {planMoney(budgets.planned_total)} = {planMoney(data.left_over)}
          <span className="block text-slate-500">Money in − Commitments − Budgets = Left over</span>
          {leftOver < 0 && (
            <span className="block mt-1">
              Commitments and Budgets come to {planMoney(String(-leftOver))} more than your money in this cycle.
            </span>
          )}
        </p>
      )}
    </>
  )
}

/** Cashflow > Plan (T-25-2): money in, commitments by group, budgets and
 *  what is left over this pay cycle. Figures are the API's; this only lays them out. */
export default function PlanView({ status, data, onRetry }: PlanViewProps) {
  return (
    <section id="plan" aria-labelledby="plan-heading" className="card-pad">
      <h2 id="plan-heading" tabIndex={-1} className="font-display font-semibold text-lg text-slate-50 focus:outline-none">Plan</h2>
      {data && <p className="text-xs text-slate-500 mt-0.5">{cycleText(data.cycle)}</p>}
      <p className="text-sm text-slate-400 mt-1 mb-3">Where this pay cycle goes. Open a line to see what is in it.</p>
      {status === 'error' ? (
        <div role="alert" className="text-sm text-slate-300">
          <p>Couldn&apos;t load your plan. Your balances and safe to spend are unaffected.</p>
          <button type="button" className="btn-ghost mt-3 min-h-[44px]" onClick={onRetry}>Try again</button>
        </div>
      ) : status === 'loading' || !data ? (
        <div role="status" className="space-y-3">
          <span className="sr-only">Loading your plan</span>
          {[0, 1, 2, 3].map((k) => <div key={k} aria-hidden className="h-10 rounded-lg bg-white/[0.04] animate-pulse" />)}
        </div>
      ) : (
        <Lines data={data} />
      )}
    </section>
  )
}
