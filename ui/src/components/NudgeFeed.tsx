import { ReactNode, useEffect, useState } from 'react'
import axios from 'axios'
import NudgeRow from './NudgeRow'
import { budgetsAPI } from '../services/api'
import { budgetNudgeId, raisedText, type NudgeRaise } from '../lib/budgets'
import { PAGE_HEADING_ID, focusTargetAfter } from '../lib/nudgeFocus'

export interface UiNudge {
  id: string
  title?: string
  body: ReactNode
  /** The arithmetic + source + as-of behind the observation, shown in a tip. */
  detail?: string
  cta?: { label: string; onClick: () => void; disabled?: boolean }
  /** "Raise to £N" (T-24-5): sets the budget's limit; the nudge then goes. */
  raise?: NudgeRaise
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
  const [raising, setRaising] = useState<string | null>(null)
  const [raiseFailed, setRaiseFailed] = useState<string | null>(null)
  const [announced, setAnnounced] = useState('')
  // undefined: nothing to move; null: the page heading; else that nudge's first button.
  const [focusNext, setFocusNext] = useState<string | null | undefined>(undefined)

  useEffect(() => {
    if (focusNext === undefined) return
    const target = focusNext === null
      ? document.getElementById(PAGE_HEADING_ID)
      : document.querySelector<HTMLElement>(`[data-nudge="${CSS.escape(focusNext)}"] button`)
    target?.focus()
    setFocusNext(undefined)
  }, [focusNext])

  const visible = nudges
    .filter((n) => !serverDismissed.has(n.id) && localStorage.getItem(key(n.id)) !== '1')
    .slice(0, MAX_VISIBLE)

  // Polite, and always rendered, so the news survives the nudge leaving.
  const liveRegion = <p role="status" aria-live="polite" className="sr-only">{announced}</p>
  if (visible.length === 0) return liveRegion

  const gone = (id: string) => setFocusNext(focusTargetAfter(visible.map((n) => n.id), id))

  const raise = (n: UiNudge) => {
    if (!n.raise) return
    const r = n.raise
    setRaising(n.id)
    setRaiseFailed(null)
    budgetsAPI
      .update(r.budgetId, { limit_pounds: r.newLimit })
      .then(() => {
        gone(n.id)
        setServerDismissed((s) => new Set(s).add(n.id))
        setAnnounced(raisedText(r))
      })
      // Demo mode cancels writes and says so in its own toast: no "Try again" here.
      .catch((e) => { if (!axios.isCancel(e)) setRaiseFailed(n.id) })
      .finally(() => setRaising(null))
  }

  const dismiss = (id: string) => {
    const budgetId = budgetNudgeId(id)
    if (budgetId) {
      // Hidden once the server has it; on a failure it stays and says so.
      const mark = (on: boolean) => setFailed((s) => { const next = new Set(s); if (on) next.add(id); else next.delete(id); return next })
      mark(false)
      budgetsAPI
        .dismissNudge(budgetId)
        .then(() => { gone(id); setServerDismissed((s) => new Set(s).add(id)) })
        .catch(() => mark(true))
      return
    }
    localStorage.setItem(key(id), '1')
    gone(id)
    setDismissedAt(Date.now())
  }

  return (
    <div className="mb-6 space-y-3" data-reveal>
      {visible.map((n) => (
        <NudgeRow key={n.id} nudge={n} dismissFailed={failed.has(n.id)} onDismiss={() => dismiss(n.id)}
          onRaise={() => raise(n)} raising={raising === n.id} raiseFailed={raiseFailed === n.id} />
      ))}
      {liveRegion}
    </div>
  )
}
