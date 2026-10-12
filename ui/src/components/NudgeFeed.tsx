import { ReactNode, useState } from 'react'
import NudgeRow from './NudgeRow'
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
  const [failed, setFailed] = useState<Set<string>>(new Set())

  const visible = nudges
    .filter((n) => !serverDismissed.has(n.id) && localStorage.getItem(key(n.id)) !== '1')
    .slice(0, MAX_VISIBLE)

  if (visible.length === 0) return null

  const dismiss = (id: string) => {
    const budgetId = budgetNudgeId(id)
    if (budgetId) {
      // Hidden once the server has it; on a failure it stays and says so.
      const mark = (on: boolean) => setFailed((s) => { const next = new Set(s); if (on) next.add(id); else next.delete(id); return next })
      mark(false)
      budgetsAPI
        .dismissNudge(budgetId)
        .then(() => setServerDismissed((s) => new Set(s).add(id)))
        .catch(() => mark(true))
      return
    }
    localStorage.setItem(key(id), '1')
    setDismissedAt(Date.now())
  }

  return (
    <div className="mb-6 space-y-3" data-reveal>
      {visible.map((n) => (
        <NudgeRow key={n.id} nudge={n} dismissFailed={failed.has(n.id)} onDismiss={() => dismiss(n.id)} />
      ))}
    </div>
  )
}
