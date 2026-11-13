import { Lightbulb } from 'lucide-react'
import InfoTip from './ui/InfoTip'
import type { UiNudge } from './NudgeFeed'

interface Props {
  nudge: UiNudge
  /** The server refused or never answered the dismissal: the nudge stays and says so. */
  dismissFailed: boolean
  onDismiss: () => void
  /** "Raise to £N" on a "will go over" nudge (T-24-5). */
  onRaise?: () => void
  raising?: boolean
  raiseFailed?: boolean
}

/** One observation in the Cashflow nudge feed. */
export default function NudgeRow({ nudge, dismissFailed, onDismiss, onRaise, raising = false, raiseFailed = false }: Props) {
  return (
    <div data-nudge={nudge.id} className="card px-4 py-3 flex flex-wrap items-center gap-3">
      <Lightbulb className="w-4 h-4 text-accent shrink-0" />
      <span className="flex-1 min-w-0 text-sm text-slate-300">
        {nudge.title && <p className="font-semibold text-slate-100">{nudge.title}</p>}
        {nudge.body}
        {nudge.detail && (
          <span className="ml-1.5 inline-flex align-middle">
            <InfoTip text={nudge.detail} side="bottom" align="left" />
          </span>
        )}
      </span>
      {/* Below sm the buttons take their own row, so the text keeps the width (mockup E1). */}
      <span className="flex flex-wrap justify-end gap-2 shrink-0 w-full sm:w-auto">
        {nudge.raise && onRaise && (
          <button data-raise="" onClick={onRaise} disabled={raising} className="btn-ghost !py-1.5 !text-accent min-h-[44px] sm:min-h-0">
            {raising ? 'Raising…' : nudge.raise.label}
          </button>
        )}
        {nudge.cta && (
          <button onClick={nudge.cta.onClick} disabled={nudge.cta.disabled} className="btn-ghost !py-1.5 !text-accent">
            {nudge.cta.label}
          </button>
        )}
        <button onClick={onDismiss} className="btn-ghost !py-1.5">
          Dismiss
        </button>
      </span>
      {raiseFailed && (
        <p role="alert" className="w-full text-sm text-neg">
          Couldn&apos;t raise the budget. Nothing was changed. Try again.
        </p>
      )}
      {dismissFailed && (
        <p role="alert" className="w-full text-sm text-neg">
          Couldn&apos;t dismiss that. Try again.
        </p>
      )}
    </div>
  )
}
