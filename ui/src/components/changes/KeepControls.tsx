import { Link } from 'react-router-dom'
import type { UndoFailure } from '../../lib/changes'

export const KEEP_FAILED_TEXT = "Couldn't keep this. Nothing was changed. Try again."
// No answer from the server: the keep may have gone through.
export const KEEP_UNCERTAIN_TEXT =
  "Couldn't confirm that. It may have been kept; check this item before you try again."
export const KEEP_CHANGED_TEXT =
  "Can't keep this: it has changed since Claude made the change. Check its current value first."

/** One row action (keep or undo) in flight or failed. Never optimistic (KP4). */
export type KeepState = { keeping: boolean; failure: UndoFailure | null }

const BUTTON = 'btn-ghost w-full sm:w-auto min-h-[44px] sm:min-h-0 shrink-0'

/** `Keep this change` (ux spec 9.2). Gone after a 409, which a retry can't fix. */
export function KeepButton({ actionKey, label, state, onKeep }: { actionKey: string; label: string; state: KeepState; onKeep: () => void }) {
  if (state.failure === 'changed') return null
  const text = state.keeping
    ? { visible: 'Keeping…', name: 'Keeping: ' }
    : state.failure
      ? { visible: 'Try again', name: 'Try again: keep ' }
      : { visible: 'Keep this change', name: 'Keep this change: ' }
  return (
    <button
      type="button"
      data-action={actionKey}
      className={BUTTON}
      onClick={onKeep}
      disabled={state.keeping}
      aria-busy={state.keeping}
      // The accessible name starts with the visible text (WCAG 2.5.3).
      aria-label={`${text.name}${label}`}
    >
      {text.visible}
    </button>
  )
}

/** The inline message after a failed keep. It never carries the server's text. */
export function KeepNotice({ alertId, failure }: { alertId: string; failure: UndoFailure | null }) {
  if (failure === null) return null
  if (failure === 'changed') {
    return (
      <div id={alertId} role="alert" tabIndex={-1} className="banner-err mt-3 text-sm outline-none">
        <p>{KEEP_CHANGED_TEXT}</p>
        <Link to="/commitments" className="btn-link mt-1 inline-flex items-center min-h-[44px] sm:min-h-0">
          Open commitments
        </Link>
      </div>
    )
  }
  return (
    <div role="alert" className="banner-err mt-3 text-sm">
      {failure === 'unknown' ? KEEP_UNCERTAIN_TEXT : KEEP_FAILED_TEXT}
    </div>
  )
}
