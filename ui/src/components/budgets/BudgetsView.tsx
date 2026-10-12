import { useState } from 'react'
import ClaudeMarker from '../changes/ClaudeMarker'
import { categoryColor } from '../../lib/categoryColors'
import { dateDayMonth } from '../../lib/format'
import {
  cycleLabel,
  footText,
  meterLabel,
  money,
  paceFraction,
  reconciliationParts,
  statusText,
  type Budget,
  type BudgetsResponse,
  type Reconciliation as ReconciliationFigures,
} from '../../lib/budgets'

export type BudgetsViewProps = {
  status: 'loading' | 'error' | 'ready'
  data: BudgetsResponse | null
  /** Connections behind on syncing (GET /banking/sync-status). */
  staleAccounts?: { name: string; last_synced_at: string }[]
  retrying?: boolean
  onRetry: () => void
  onSuggest: () => void
  /** The existing drill-down to a category's transactions. */
  onOpenCategory: (category: string) => void
}

const NO_PAYDAY =
  'Budgets follow your pay cycle. Set your payday on Commitments to line them up; until then this uses the last 30 days.'
const NO_RECONCILIATION = "Budgets can't be compared to safe to spend until a payday is set."

/**
 * Spending > Budgets, this cycle (concept 4.2, 5, 9). Budgets watch
 * purchases; they never change safe to spend, so the reconciliation line is
 * information only. Every figure is shown as the API sent it.
 */
export default function BudgetsView(props: BudgetsViewProps) {
  const { status, data, staleAccounts = [], retrying = false, onRetry, onSuggest, onOpenCategory } = props
  if (status === 'loading') {
    return (
      <div className="card card-pad">
        <span role="status" className="sr-only">Loading budgets…</span>
        <div aria-hidden="true" className="space-y-6">
          {[0, 1, 2].map((i) => (
            <div key={i} data-skeleton className="space-y-2 motion-safe:animate-pulse">
              <div className="h-4 w-1/2 rounded bg-white/[0.06]" />
              <div className="h-2 w-full rounded-full bg-white/[0.06]" />
            </div>
          ))}
        </div>
      </div>
    )
  }
  if (status === 'error' || !data) {
    return (
      <div role="alert" className="banner-err flex flex-col sm:flex-row sm:items-center gap-3">
        <p className="flex-1">Couldn&apos;t load your budgets. Your spending is unaffected. Try again.</p>
        <button type="button" className="btn-ghost min-h-[44px] sm:min-h-0" onClick={onRetry} disabled={retrying} aria-busy={retrying}>
          {retrying ? 'Trying…' : 'Try again'}
        </button>
      </div>
    )
  }

  const tracked = data.budgets.filter((b) => !b.paused)
  if (data.budgets.length === 0) {
    return (
      <div className="card card-pad text-center py-8">
        <h2 className="font-display font-semibold text-lg text-slate-100">
          Set a limit for the things you want to keep an eye on.
        </h2>
        <p className="text-sm text-slate-400 mt-2">Budgets follow your pay cycle and never change your safe to spend.</p>
        <button type="button" className="btn-primary mt-4 min-h-[44px] sm:min-h-0" onClick={onSuggest}>
          Suggest budgets
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{cycleLabel(data.cycle)}</p>
      {data.cycle.fallback && <p className="text-xs text-slate-400">{NO_PAYDAY}</p>}
      {staleAccounts.map((a) => (
        <p key={a.name} className="text-xs text-warn">
          Budgets may be behind: {a.name} hasn&apos;t synced since {dateDayMonth(a.last_synced_at)}.
        </p>
      ))}
      <div className="grid grid-cols-1 lg:grid-cols-[1.35fr_1fr] gap-4 lg:gap-5 items-start">
        <div className="card card-pad">
          <h2 id="budgets-heading" tabIndex={-1} className="font-display font-semibold text-slate-100 outline-none">
            Budgets
          </h2>
          <p className="text-xs text-slate-400 mt-1 mb-5">
            Measuring purchases. <span className="text-slate-300">Not counted here:</span> commitments, transfers, card
            payoffs.
          </p>
          <ul className="space-y-5">
            {tracked.length === 0 && (
              <li className="text-sm text-slate-400">All your budgets are paused. Their spending counts under Everything else.</li>
            )}
            {tracked.map((b, i) => (
              <BudgetRow key={b.id} budget={b} color={categoryColor(i)} daysLeft={data.cycle.days_left} onOpen={onOpenCategory} />
            ))}
            <li>
              <div className="flex justify-between gap-3 text-sm">
                <span className="font-medium text-slate-300">Everything else</span>
                <span className="tnum font-semibold text-slate-100">
                  {money(data.other_spending)} <span className="font-normal text-slate-400">no budget</span>
                </span>
              </div>
              <button type="button" className="btn-link text-xs mt-1 min-h-[44px] sm:min-h-0" onClick={onSuggest}>
                Set a budget
              </button>
            </li>
          </ul>
        </div>
        <Reconciliation data={data} figures={data.cycle.fallback ? null : data.reconciliation} />
      </div>
    </div>
  )
}

function BudgetRow({ budget: b, color, daysLeft, onOpen }: { budget: Budget; color: string; daysLeft: number; onOpen: (c: string) => void }) {
  const spent = Number(b.spent)
  const over = b.status === 'over'
  const fill = b.limit_pounds > 0 ? Math.min(spent / b.limit_pounds, 1) * 100 : 0
  const pace = paceFraction(b)
  return (
    <li>
      <div className="flex justify-between gap-3 text-sm mb-2">
        <span className="flex items-center gap-2 min-w-0 flex-wrap">
          <button
            type="button"
            className="font-medium text-slate-300 hover:text-slate-100 text-left [overflow-wrap:anywhere] min-h-[44px] sm:min-h-0"
            aria-label={`${b.category}: see transactions`}
            onClick={() => onOpen(b.category)}
          >
            {b.category}
          </button>
          {b.changed_by_claude && <ClaudeMarker auditId={b.changed_by_claude.audit_id} />}
        </span>
        <span className="tnum font-semibold text-slate-100 shrink-0">
          {money(spent)} <span className="font-normal text-slate-400">of {money(b.limit_pounds)}</span>
        </span>
      </div>
      <div
        role="meter"
        aria-valuenow={Math.min(spent, b.limit_pounds)}
        aria-valuemin={0}
        aria-valuemax={b.limit_pounds}
        aria-label={meterLabel(b, daysLeft)}
        className="relative h-2 rounded-full bg-white/[0.06]"
      >
        <div data-fill className="h-2 rounded-full motion-safe:transition-[width]" style={{ width: `${fill}%`, backgroundColor: color }} />
        <span
          data-pace
          aria-hidden="true"
          className="absolute -top-1 h-4 w-0.5 rounded bg-slate-100/85"
          style={{ left: `calc(${pace * 100}% - 1px)` }}
        />
        {over && (
          <span aria-hidden="true" className="absolute -right-[3px] -top-[3px] h-3.5 w-1.5 rounded-sm border-[1.5px] border-slate-200 bg-ink-900" />
        )}
      </div>
      <div className="flex justify-between gap-3 mt-1.5 text-xs text-slate-400">
        <span>{over ? <span className="chip-out">{statusText(b)}</span> : statusText(b)}</span>
        <span className="tnum">{footText(b, daysLeft)}</span>
      </div>
    </li>
  )
}

function Reconciliation({ data, figures }: { data: BudgetsResponse; figures: ReconciliationFigures | null }) {
  const [open, setOpen] = useState(false)
  const parts = reconciliationParts(figures)
  return (
    <div className="card card-pad space-y-3">
      <h2 className="font-display font-semibold text-slate-100">How this fits with safe to spend</h2>
      {parts ? (
        <>
          <p className="text-sm text-slate-300 leading-relaxed">
            Safe to spend <b className="tnum text-slate-100">{parts.safe}</b> <Op>−</Op>{' '}
            <b className="tnum text-slate-100">{parts.left}</b> left in your budgets <Op>−</Op>{' '}
            <b className="tnum text-slate-100">{parts.other}</b> other spending at your pace <Op>=</Op>{' '}
            <b className="tnum text-accent">{parts.headroom}</b> headroom
          </p>
          <p className="text-xs text-slate-400">Information only. Your safe to spend is unchanged.</p>
        </>
      ) : (
        <p className="text-xs text-slate-400">{NO_RECONCILIATION}</p>
      )}
      <div>
        <button
          type="button"
          className="btn-link text-sm min-h-[44px] sm:min-h-0"
          aria-expanded={open}
          aria-controls="budgets-not-counted"
          onClick={() => setOpen((o) => !o)}
        >
          Not counted here
        </button>
        {open && (
          <dl id="budgets-not-counted" className="mt-2 space-y-1.5 text-sm">
            <NotCounted label="Matched to commitments" value={data.not_counted.commitments} />
            <NotCounted label="Transfers between your accounts" value={data.not_counted.transfers} />
            <NotCounted label="Card payoffs" value={data.not_counted.card_payoffs} />
            {Number(data.not_counted.financed) > 0 && (
              <NotCounted label="Moved to a payment plan" value={data.not_counted.financed} />
            )}
          </dl>
        )}
      </div>
    </div>
  )
}

const Op = ({ children }: { children: string }) => <span className="text-slate-400 mx-0.5">{children}</span>

function NotCounted({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-400">{label}</dt>
      <dd className="tnum text-slate-100">{money(value)}</dd>
    </div>
  )
}
