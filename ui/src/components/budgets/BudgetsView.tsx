import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import ClaudeMarker from '../changes/ClaudeMarker'
import PaidBackByOthers from './PaidBackByOthers'
import { categoryColor } from '../../lib/categoryColors'
import { dateDayMonth, gbp } from '../../lib/format'
import { barGeometry, comingUpA11y, comingUpLine, overByPaydayText, takesYouOverLine } from '../../lib/budgetBar'
import {
  cycleLabel,
  footText,
  meterLabel,
  money,
  budgetsBox,
  statusText,
  type Budget,
  type BudgetsResponse,
  type SummaryThisCycle,
} from '../../lib/budgets'

export type BudgetsViewProps = {
  status: 'loading' | 'error' | 'ready'
  data: BudgetsResponse | null
  /** Connections behind on syncing (GET /banking/sync-status). */
  staleAccounts?: { name: string; last_synced_at: string }[]
  retrying?: boolean
  onRetry: () => void
  onSuggest: () => void
  /** Opens Manage budgets (T-09-7); the button shows only when given. */
  onManage?: () => void
  /** The existing drill-down to a category's transactions. */
  onOpenCategory: (category: string) => void
}

const NO_PAYDAY =
  'Budgets follow your pay cycle. Set your payday on Commitments to line them up; until then this uses the last 30 days.'

/**
 * Spending > Budgets, this cycle (concept 4.2, 5, 9). Budgets watch
 * purchases; they never change safe to spend, and the "Your budgets" box
 * says so in plain words (12a). Every figure is shown as the API sent it.
 */
export default function BudgetsView(props: BudgetsViewProps) {
  const { status, data, staleAccounts = [], retrying = false, onRetry, onSuggest, onManage, onOpenCategory } = props
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
          <div className="flex items-center justify-between gap-3">
            <h2 id="budgets-heading" tabIndex={-1} className="font-display font-semibold text-slate-100 outline-none">
              Budgets
            </h2>
            {onManage && (
              <button type="button" className="btn-ghost !px-3 !py-1.5 text-sm min-h-[44px] sm:min-h-0" onClick={onManage}>
                Manage budgets
              </button>
            )}
          </div>
          <p className="text-xs text-slate-400 mt-1 mb-5">
            Measuring purchases and commitments you have paid. <span className="text-slate-300">Not counted here:</span>{' '}
            commitments with no budget, transfers, card payoffs.
          </p>
          <ul className="space-y-5">
            {tracked.length === 0 && (
              <li className="text-sm text-slate-400">All your budgets are paused. Their spending counts under Everything else.</li>
            )}
            {tracked.map((b) => (
              // Colour by position among all budgets, as in Manage, so a budget keeps its colour when another pauses.
              <BudgetRow key={b.id} budget={b} color={categoryColor(data.budgets.indexOf(b))} daysLeft={data.cycle.days_left} onOpen={onOpenCategory} />
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
        <BudgetsBox data={data} summary={data.summary_this_cycle} allPaused={tracked.length === 0} />
      </div>
    </div>
  )
}

function BudgetRow({ budget: b, color, daysLeft, onOpen }: { budget: Budget; color: string; daysLeft: number; onOpen: (c: string) => void }) {
  const spent = Number(b.spent)
  const over = b.status === 'over'
  const geo = barGeometry(b)
  const comingUp = comingUpLine(b)
  const overByPayday = overByPaydayText(b)
  const takesYouOver = takesYouOverLine(b)
  const a11y = comingUpA11y(b)
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
        aria-label={a11y ? `${meterLabel(b, daysLeft)}, ${a11y}` : meterLabel(b, daysLeft)}
        className={`relative h-2 rounded-full bg-white/[0.06] ${geo.marker !== null ? 'mt-6' : ''}`}
      >
        <div data-fill className="h-2 rounded-full motion-safe:transition-[width]" style={{ width: `${geo.fill}%`, backgroundColor: color }} />
        {geo.segment > 0 && (
          <span data-coming aria-hidden="true" className="absolute top-0 h-2 rounded-r-full" style={{ left: `${geo.segmentStart}%`, width: `${geo.segment}%`, ...COMING_HATCH }} />
        )}
        <span
          data-pace
          aria-hidden="true"
          className="absolute -top-1 h-4 w-0.5 rounded bg-slate-100/85"
          style={{ left: `calc(${geo.pace}% - 1px)` }}
        />
        {geo.marker !== null && (
          <>
            <span data-limit aria-hidden="true" className="absolute -top-1.5 h-5 w-0.5 bg-slate-50" style={{ left: `${geo.marker}%` }} />
            {/* Centred on the marker, kept 20px inside each end of the bar. */}
            <span aria-hidden="true" className="absolute -top-6 -translate-x-1/2 text-[11px] font-semibold text-slate-100 tnum"
              style={{ left: `clamp(20px, ${geo.marker}%, calc(100% - 20px))` }}>
              {money(b.limit_pounds)}
            </span>
          </>
        )}
        {over && geo.marker === null && (
          <span data-endcap aria-hidden="true" className="absolute -right-[3px] -top-[3px] h-3.5 w-1.5 rounded-sm border-[1.5px] border-slate-200 bg-ink-900" />
        )}
      </div>
      {comingUp && <ComingUpLine budget={b} line={comingUp} />}
      {takesYouOver && <p className="mt-1 text-xs text-slate-300">{takesYouOver}</p>}
      <div className="flex flex-wrap justify-between gap-x-3 gap-y-0.5 mt-1.5 text-xs text-slate-400">
        <span>
          {over ? <span className="chip-out">{statusText(b)}</span>
            : b.status === 'budget_used' ? <span className="chip">{statusText(b)}</span>
            : statusText(b)}
          {overByPayday && ` · ${overByPayday}`}
        </span>
        <span className="tnum">{footText(b, daysLeft)}</span>
      </div>
    </li>
  )
}

/** Warn-amber hatch with a dashed outline (3:1 non-text contrast): coming up, not spent. */
const COMING_HATCH = {
  backgroundImage: 'repeating-linear-gradient(135deg, rgba(251,191,36,0.6) 0 3px, rgba(251,191,36,0.16) 3px 6px)',
  outline: '1px dashed rgba(251,191,36,0.9)',
  outlineOffset: '-1px',
}

/** "£192.00 coming up: Meal kit, 3 more this cycle": a disclosure listing each instalment. */
function ComingUpLine({ budget: b, line }: { budget: Budget; line: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div className="mt-1.5">
      <button type="button" className="text-xs text-slate-300 hover:text-slate-100 hover:underline underline-offset-2 inline-flex items-center gap-1.5 text-left min-h-[44px] sm:min-h-0"
        aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <span aria-hidden="true" className="inline-block h-2.5 w-3.5 rounded-sm shrink-0" style={COMING_HATCH} />
        <span>{line}</span>
      </button>
      <ul id={id} hidden={!open} className="mt-1 space-y-1 text-xs">
        {(b.coming_up?.items ?? []).map((i) => (
          <li key={`${i.commitment_id}-${i.due_date}`} className="flex justify-between gap-3">
            <span className="text-slate-300 [overflow-wrap:anywhere]">{i.label} <span className="text-slate-400">{dateDayMonth(i.due_date)}</span></span>
            <span className="tnum text-slate-200">{gbp(Number(i.amount))}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** "Your budgets" (concept 12a, BX1-BX6): a plain summary, figures as received, no arithmetic. */
function BudgetsBox({ data, summary, allPaused }: { data: BudgetsResponse; summary: SummaryThisCycle | null; allPaused: boolean }) {
  const [open, setOpen] = useState(false)
  const box = summary ? budgetsBox(summary, allPaused) : null
  return (
    <div id="budgets-box" className="card card-pad space-y-3">
      <h2 className="font-display font-semibold text-slate-100">Your budgets</h2>
      {box && (
        <div className="space-y-1.5">
          <p className="text-sm text-slate-200 tnum">{box.line1}</p>
          <p className="text-sm text-slate-400">{box.line2}</p>
          {box.paused && <p className="text-xs text-slate-400">{box.paused}</p>}
        </div>
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
        <div hidden={!open}>
          <dl id="budgets-not-counted" className="mt-2 space-y-1.5 text-sm">
            <NotCounted label="Commitments with no budget" value={data.not_counted.commitments}
              link={<Link to="/dashboard#plan" className="btn-link !text-xs">See in Plan</Link>} />
            {Number(data.not_counted.commitments_no_category ?? 0) > 0 && (
              <NotCounted label="Commitments with no category" value={data.not_counted.commitments_no_category ?? 0} />
            )}
            <NotCounted label="Transfers between your accounts" value={data.not_counted.transfers} />
            <NotCounted label="Card payoffs" value={data.not_counted.card_payoffs} />
            {Number(data.not_counted.financed) > 0 && (
              <NotCounted label="Moved to a payment plan" value={data.not_counted.financed} />
            )}
          </dl>
          <PaidBackByOthers notCounted={data.not_counted} />
        </div>
      </div>
    </div>
  )
}

function NotCounted({ label, value, link }: { label: string; value: number | string; link?: ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-400">{label}{link && <> {link}</>}</dt>
      <dd className="tnum text-slate-100">{money(value)}</dd>
    </div>
  )
}
