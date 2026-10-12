import { Lightbulb } from 'lucide-react'
import InfoTip from './ui/InfoTip'
import type { UiNudge } from './NudgeFeed'

interface Props {
  nudge: UiNudge
  /** The server refused or never answered the dismissal: the nudge stays and says so. */
  dismissFailed: boolean
  onDismiss: () => void
}

/** One observation in the Cashflow nudge feed. */
export default function NudgeRow({ nudge, dismissFailed, onDismiss }: Props) {
  return (
    <div className="card px-4 py-3 flex flex-wrap items-center gap-3">
      <Lightbulb className="w-4 h-4 text-accent shrink-0" />
      <span className="flex-1 min-w-0 text-sm text-slate-300">
        {nudge.body}
        {nudge.detail && (
          <span className="ml-1.5 inline-flex align-middle">
            <InfoTip text={nudge.detail} side="bottom" align="left" />
          </span>
        )}
      </span>
      <span className="flex gap-2 shrink-0">
        {nudge.cta && (
          <button onClick={nudge.cta.onClick} disabled={nudge.cta.disabled} className="btn-ghost !py-1.5 !text-accent">
            {nudge.cta.label}
          </button>
        )}
        <button onClick={onDismiss} className="btn-ghost !py-1.5">
          Dismiss
        </button>
      </span>
      {dismissFailed && (
        <p role="alert" className="w-full text-sm text-neg">
          Couldn&apos;t dismiss that. Try again.
        </p>
      )}
    </div>
  )
}
