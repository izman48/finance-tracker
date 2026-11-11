/** Paid-back marks in the UI (T-03-6). */

/** Where focus goes after an undo of `doneId` (AC-34): the next Undo still
 *  shown, else null, meaning something that stays (the sheet's title). */
export function nextUndoAfter(undoIds: string[], doneId: string): string | null {
  const rest = undoIds.filter((id) => id !== doneId)
  if (rest.length === 0) return null
  const at = undoIds.indexOf(doneId)
  return rest[Math.min(Math.max(at, 0), rest.length - 1)]
}
