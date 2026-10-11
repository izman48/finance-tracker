/**
 * "Keep this change" (T-08-20; ux spec section 9, income scope). Income
 * Claude raised or confirmed doesn't count in savable until the user keeps
 * it here. Expense changes wait on owner decision D5, so only income rows
 * ever get the control.
 */
import type { Commitment } from '../types'
import { gbp } from './format'

export const KEEP_PENDING_TEXT = 'Not counted in savable until you keep it.'
// A dismissed income is out of savable at once; only the payday it sets is held (ux spec 9.3, KP15b).
const KEEP_DISMISSED_TEXT =
  'Claude dismissed this. Your safe to spend still uses it to find your payday until you keep this change. It no longer counts in savable.'

export const pendingText = (dismissed: boolean) => (dismissed ? KEEP_DISMISSED_TEXT : KEEP_PENDING_TEXT)

export const keepToast = (label: string, dismissed = false) =>
  dismissed ? `Kept “${label}”. Your safe to spend now reflects it.` : `Kept “${label}”. It now counts in your savable.`

/** The line under savable (KP10), or null when nothing is held back. */
export function savableNote(total: number | string | undefined): string | null {
  const amount = Number(total ?? 0)
  if (!(amount > 0)) return null
  return `${gbp(amount)} of income Claude added isn't counted in savable until you keep it.`
}

/** Whether a commitment row shows the pending line, Keep and Undo (KP1, KP13). */
export function canKeep(c: Commitment): boolean {
  return c.direction === 'income' && c.keep === 'pending' && (c.keep_audit_ids?.length ?? 0) > 0
}

/**
 * Keep (oldest first) or undo (newest first) each row in turn. A refusal
 * before anything went through is passed on as it came (so "nothing was
 * changed" holds); after one went through it is re-thrown without a
 * status, which the row shows as an unknown outcome.
 */
export async function postEach(ids: string[], post: (id: string) => Promise<unknown>): Promise<void> {
  for (const [i, id] of ids.entries()) {
    try {
      await post(id)
    } catch (err) {
      if (i === 0) throw err
      throw new Error('partly done')
    }
  }
}

/**
 * Whether a listed commitment adds to its list's total. A dismissal Claude
 * made that is still pending keep is listed (9.3) but not added: savable
 * already leaves a dismissed income out; only the payday it sets is held.
 */
export const countsInListTotal = (c: Commitment) => c.status !== 'dismissed'
