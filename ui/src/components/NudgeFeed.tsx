import { ReactNode, useState } from 'react'
import { Lightbulb } from 'lucide-react'
import InfoTip from './ui/InfoTip'
import { budgetsAPI } from '../services/api'
import { budgetNudgeId } from '../lib/budgets'

export interface UiNudge {
  id: string
  body: ReactNode
  /** The arithmetic + source + as-of behind the observation, shown in a tip. */
  detail?: string
  cta?: { label: string; onClick: () => void; disabled?: boolean }
}

const MAX_VISIBLE = 3
const key = (id: string) => `nudge.${id}.dismissed`

/** The Cashflow nudge feed: a few honest, dismissible observations. Each one
 *  is a fact with its calculation visible — never a recommendation. Dismissals
 *  are per-nudge and local to this browser, except budget nudges (`budget-…`),
 *  which fire once per cycle and are dismissed on the server (T-09-8). */
export default function NudgeFeed({ nudges }: { nudges: UiNudge[] }) {
  const [dismissedAt, setDismissedAt] = useState(0) // bump to re-read localStorage
  void dismissedAt
  const [serverDismissed, setServerDismissed] = useState<Set<string>>(new Set())

  const visible = nudges
    .filter((n) => !serverDismissed.has(n.id) && localStorage.getItem(key(n.id)) !== '1')
    .slice(0, MAX_VISIBLE)

  if (visible.length === 0) return null

  const dismiss = (id: string) => {
    const budgetId = budgetNudgeId(id)
    if (budgetId) {
      // Hidden once the server has it; on a failure it simply stays.
      budgetsAPI
        .dismissNudge(budgetId)
        .then(() => setServerDismissed((s) => new Set(s).add(id)))
        .catch(() => {})
      return
    }
    localStorage.setItem(key(id), '1')
    setDismissedAt(Date.now())
  }

  return (
    <div className="mb-6 space-y-3" data-reveal>
      {visible.map((n) => (
        <div key={n.id} className="card px-4 py-3 flex flex-wrap items-center gap-3">
          <Lightbulb className="w-4 h-4 text-accent shrink-0" />
          <span className="flex-1 min-w-0 text-sm text-slate-300">
            {n.body}
            {n.detail && (
              <span className="ml-1.5 inline-flex align-middle">
                <InfoTip text={n.detail} side="bottom" align="left" />
              </span>
            )}
          </span>
          <span className="flex gap-2 shrink-0">
            {n.cta && (
              <button onClick={n.cta.onClick} disabled={n.cta.disabled} className="btn-ghost !py-1.5 !text-accent">
                {n.cta.label}
              </button>
            )}
            <button onClick={() => dismiss(n.id)} className="btn-ghost !py-1.5">
              Dismiss
            </button>
          </span>
        </div>
      ))}
    </div>
  )
}
