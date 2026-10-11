import { Link } from 'react-router-dom'
import type { UndoFailure } from '../../lib/changes'
import { canKeep, pendingLine, safeToSpendNote, savableNote } from '../../lib/keep'
import type { Commitment } from '../../types'
import { CHANGED_SINCE_TEXT, RATE_LIMIT_TEXT, UNDO_FAILED_TEXT, UNDO_UNCERTAIN_TEXT } from './UndoControls'

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

/** The commitment row's undo message: the Changes screen's copy, without its link back here. */
function RowUndoNotice({ alertId, failure }: { alertId: string; failure: UndoFailure | null }) {
  if (failure === null) return null
  const textOf = { changed: CHANGED_SINCE_TEXT, unknown: UNDO_UNCERTAIN_TEXT, other: UNDO_FAILED_TEXT, rate: UNDO_FAILED_TEXT + RATE_LIMIT_TEXT }
  return (
    <div id={alertId} role="alert" tabIndex={-1} className="banner-err mt-3 text-sm outline-none">
      {textOf[failure]}
    </div>
  )
}

type Props = {
  c: Commitment
  keep: KeepState
  undo: KeepState
  onKeep: (c: Commitment) => void
  onUndo: (c: Commitment) => void
}

/**
 * Under a pending income's `Changed by Claude` chip (ux spec 9.1, KP1): the
 * pending line, `Keep this change` and `Undo`. Once the server says it is
 * kept or no longer held, only a "changed since" message can remain.
 */
export function CommitmentKeep({ c, keep, undo, onKeep, onUndo }: Props) {
  const pending = canKeep(c)
  if (!pending && keep.failure !== 'changed' && undo.failure !== 'changed') return null
  // Undo takes back every pending change Claude made to it, newest first.
  const undoName = `Claude’s changes to “${c.label}”`
  const undoText = undo.keeping
    ? { visible: 'Undoing…', name: 'Undoing: ' }
    : undo.failure
      ? { visible: 'Try again', name: 'Try again: undo ' }
      : { visible: 'Undo', name: 'Undo: ' }
  return (
    <div className="basis-full min-w-0">
      {pending && (
        <>
          <p className="text-xs text-slate-400">{pendingLine(c)}</p>
          <div className="mt-2 flex flex-col sm:flex-row gap-2">
            <KeepButton actionKey={`keep-${c.id}`} label={c.label} state={keep} onKeep={() => onKeep(c)} />
            {undo.failure !== 'changed' && (
              <button
                type="button"
                data-action={`undo-${c.id}`}
                className={BUTTON}
                onClick={() => onUndo(c)}
                disabled={undo.keeping}
                aria-busy={undo.keeping}
                aria-label={`${undoText.name}${undoName}`}
              >
                {undoText.visible}
              </button>
            )}
          </div>
        </>
      )}
      <KeepNotice alertId={`commitment-${c.id}-keep-alert`} failure={pending || keep.failure === 'changed' ? keep.failure : null} />
      <RowUndoNotice alertId={`commitment-${c.id}-undo-alert`} failure={pending || undo.failure === 'changed' ? undo.failure : null} />
    </div>
  )
}

/**
 * One plain line under a held figure while something is waiting to be kept
 * (ux spec 9.2). Home's cards are links already, so there it has no Review.
 */
function HeldNote({ note, review }: { note: string | null; review: boolean }) {
  if (!note) return null
  return (
    <p className="text-xs text-slate-400 mt-1">
      {note}
      {review && (
        <>
          {' '}
          <Link to="/commitments" className="text-accent hover:underline">
            Review
          </Link>
        </>
      )}
    </p>
  )
}

/** Under savable (KP10). */
export function SavableNote({ total, review = true }: { total: number | string | undefined; review?: boolean }) {
  return <HeldNote note={savableNote(total)} review={review} />
}

/** Under safe to spend (KP19). */
export function SafeToSpendNote({ total, review = true }: { total: number | string | undefined; review?: boolean }) {
  return <HeldNote note={safeToSpendNote(total)} review={review} />
}
