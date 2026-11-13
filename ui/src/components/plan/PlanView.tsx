import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import {
  budgetLine, budgetsSubline, cycleText, fixedSubline, incomeSubline, itemStatus, planMoney,
  type PlanResponse,
} from '../../lib/plan'

export interface PlanViewProps {
  status: 'loading' | 'error' | 'ready'
  data: PlanResponse | null
  onRetry: () => void
}

const rowClass = 'w-full min-h-[44px] flex items-center gap-2 py-2 text-left text-sm'

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
  const chip = status.startsWith('Paid') || status === 'Received' ? 'chip-pos' : 'chip'
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
  const { income, fixed, budgets } = data
  const hasIncome = income.items.length > 0
  const outsideOver = Number(data.outside_vs_not_planned) > 0
  return (
    <>
      <div className="divide-y divide-white/[0.06]">
        {hasIncome ? (
          <Row label="Income" sub={incomeSubline(income)} amount={planMoney(income.total)}>
            <ul>{income.items.map((i) => <Item key={i.id} label={i.label} status={itemStatus(i.status, i.date)} amount={planMoney(i.amount)} />)}</ul>
          </Row>
        ) : (
          <Empty label="Income" note="No income found this cycle" to="/commitments" action="Check your income" />
        )}
        {fixed.groups.length > 0 ? (
          <Row label="Fixed" sub={fixedSubline(fixed)} amount={planMoney(fixed.total)}>
            {fixed.groups.map((g) => (
              <Row key={g.category ?? ''} label={g.category ?? 'No category'} sub={`${g.paid_count} of ${g.count} paid`} amount={planMoney(g.total)}>
                <ul>
                  {g.items.map((c) => (
                    <Item key={`${c.commitment_id}-${c.due_date}`} label={c.label} status={itemStatus(c.status, c.due_date)}
                      amount={planMoney(c.status === 'not_due_this_cycle' ? '0' : c.amount)} />
                  ))}
                </ul>
              </Row>
            ))}
          </Row>
        ) : (
          <Empty label="Fixed" note="Nothing scheduled" to="/commitments" action="Add a commitment" />
        )}
        {budgets.items.length > 0 ? (
          <Row label="Budgets" sub={budgetsSubline(budgets)} amount={planMoney(budgets.limits_total)}>
            {budgets.items.map((b) => (
              <Row key={b.budget_id} label={b.category} sub={budgetLine(b)} amount={planMoney(b.limit)}>
                <ul>
                  {b.commitments.filter((c) => c.status === 'paid').map((c) => (
                    <Item key={`${c.commitment_id}-${c.date}`} label={c.label} status={itemStatus(c.status, c.date)} amount={planMoney(c.amount)} />
                  ))}
                  <Item label="Other purchases" status="Paid" amount={planMoney(b.other_purchases)} />
                  {b.commitments.filter((c) => c.status === 'due').map((c) => (
                    <Item key={`${c.commitment_id}-${c.date}`} label={c.label} status={itemStatus(c.status, c.date)} amount={planMoney(c.amount)} />
                  ))}
                </ul>
              </Row>
            ))}
          </Row>
        ) : (
          <Empty label="Budgets" note="No budgets set" to="/insights?section=budgets" action="Suggest budgets" />
        )}
        {hasIncome && <Row label="Not planned" sub="What is left after Fixed and Budgets" amount={planMoney(data.not_planned)} />}
      </div>

      <div className="mt-4 rounded-xl bg-white/[0.03] px-3 py-3 text-sm">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-slate-300">Spent so far in categories with no budget</span>{' '}
          <span className="shrink-0 tnum text-slate-100">{planMoney(data.spent_outside_budgets)}</span>
        </div>
        {hasIncome && outsideOver && (
          <p className="mt-1 text-xs text-slate-400">
            That is {planMoney(data.outside_vs_not_planned)} more than the {planMoney(data.not_planned)} left.
          </p>
        )}
      </div>

      {hasIncome && (
        <p className="mt-4 text-xs text-slate-400 tnum">
          {planMoney(income.total)} − {planMoney(fixed.total)} − {planMoney(budgets.limits_total)} = {planMoney(data.not_planned)}
          <span className="block text-slate-500">Income − Fixed − Budget limits = Not planned</span>
        </p>
      )}
    </>
  )
}

/** Cashflow > Plan (T-24-6): income, every commitment and every budget for
 *  the pay cycle. Figures are the API's; this only lays them out. */
export default function PlanView({ status, data, onRetry }: PlanViewProps) {
  return (
    <section id="plan" aria-labelledby="plan-heading" className="card-pad">
      <h2 id="plan-heading" tabIndex={-1} className="font-display font-semibold text-lg text-slate-50 focus:outline-none">Plan</h2>
      {data && <p className="text-xs text-slate-500 mt-0.5">{cycleText(data.cycle)}</p>}
      <p className="text-sm text-slate-400 mt-1 mb-3">Where this pay cycle goes. Every line opens to the transactions behind it.</p>
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
