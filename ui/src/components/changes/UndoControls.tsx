import { Link } from 'react-router-dom'
import { changeTitle, type AuditItem, type UndoFailure } from '../../lib/changes'

export const CHANGED_SINCE_TEXT =
  "Can't undo this: it has changed since Claude made the change. Check its current value and change it by hand if you need to."
export const UNDO_FAILED_TEXT = "Couldn't undo this. Nothing was changed. Try again."
export const RATE_LIMIT_TEXT = " You've reached the hourly limit; try again later."
// No answer from the server: the undo may have gone through, so don't claim otherwise.
export const UNDO_UNCERTAIN_TEXT =
  "Couldn't confirm the undo. It may have gone through; check this change before you try again."

export type UndoState = { undoing: boolean; failure: UndoFailure | null }

/**
 * The row's Undo button (ux spec 1.5). Gone once the server says the change
 * is undone, and for this session after a "changed since" refusal, which a
 * retry can never fix.
 */
export function UndoButton({ item, state, onUndo }: { item: AuditItem; state: UndoState; onUndo: (item: AuditItem) => void }) {
  if (item.undone_at !== null || state.failure === 'changed') return null
  const label = state.undoing
    ? { visible: 'Undoing…', name: 'Undoing: ' }
    : state.failure
      ? { visible: 'Try again', name: 'Try again: undo ' }
      : { visible: 'Undo', name: 'Undo: ' }
  return (
    <button
      type="button"
      data-undo={item.id}
      className="btn-ghost w-full sm:w-auto min-h-[44px] sm:min-h-0 shrink-0"
      onClick={() => onUndo(item)}
      disabled={state.undoing}
      aria-busy={state.undoing}
      // The accessible name starts with the visible text (WCAG 2.5.3).
      aria-label={`${label.name}${changeTitle(item)}`}
    >
      {label.visible}
    </button>
  )
}

/** The inline message after a failed undo. It never carries the server's text. */
export function UndoNotice({ item, failure }: { item: AuditItem; failure: UndoFailure | null }) {
  if (failure === null) return null
  // A refetch showed the undo went through after all: the Undone chip says so.
  if (item.undone_at !== null && failure !== 'changed') return null
  if (failure === 'changed') {
    const commitments = item.target_kind === 'commitment'
    return (
      <div id={`change-${item.id}-alert`} role="alert" tabIndex={-1} className="banner-err mt-3 text-sm outline-none">
        <p>{CHANGED_SINCE_TEXT}</p>
        <Link
          to={commitments ? '/commitments' : '/dashboard'}
          className="btn-link mt-1 inline-flex items-center min-h-[44px] sm:min-h-0"
        >
          {commitments ? 'Open commitments' : 'Open planned events'}
        </Link>
      </div>
    )
  }
  return (
    <div role="alert" className="banner-err mt-3 text-sm">
      {failure === 'unknown' ? UNDO_UNCERTAIN_TEXT : UNDO_FAILED_TEXT}
      {failure === 'rate' && RATE_LIMIT_TEXT}
    </div>
  )
}
