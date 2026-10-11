/**
 * "Keep this change" (T-08-20, T-08-21b; ux spec section 9). Nothing Claude
 * changes raises savable (income it raised or confirmed) or safe to spend
 * (bills it dismissed, lowered or moved later) until the user keeps it here.
 */
import type { Commitment } from '../types'
import type { AuditItem } from './changes'
import { dateDayMonth, gbp } from './format'

export const KEEP_PENDING_TEXT = 'Not counted in savable until you keep it.'
// A dismissed income is out of savable at once; only the payday it sets is held (ux spec 9.3, KP15b).
const KEEP_DISMISSED_TEXT =
  'Claude dismissed this. Your safe to spend still uses it to find your payday until you keep this change. It no longer counts in savable.'

const STILL_COUNTED = 'until you keep this change.'
const CUT_DISMISSED = `Claude dismissed this. It still counts in your safe to spend ${STILL_COUNTED}`
const CUT_SEVERAL = `Still counted in your safe to spend ${STILL_COUNTED}`
const loweredLine = (before: number | string, after: number | string) =>
  `Claude lowered this from ${gbp(Number(before))} to ${gbp(Number(after))}. It still counts at ${gbp(Number(before))} in your safe to spend ${STILL_COUNTED}`
const movedLine = (before: string, after: string) =>
  `Claude moved this from ${dateDayMonth(before)} to ${dateDayMonth(after)}. It still counts on ${dateDayMonth(before)} in your safe to spend ${STILL_COUNTED}`

/** The pending line under a commitment row (9.2, KP15, KP18). */
export function pendingLine(c: Commitment): string {
  const dismissed = c.status === 'dismissed'
  if (c.keep_kind !== 'expense_cut') return dismissed ? KEEP_DISMISSED_TEXT : KEEP_PENDING_TEXT
  if (dismissed) return CUT_DISMISSED
  // held_* are set only for a field Claude changed that still differs (eng-b's shape).
  const amount = c.held_amount ?? null
  const date = c.held_next_date ?? null
  if (amount !== null && date === null) return loweredLine(amount, c.amount)
  if (date !== null && amount === null) return movedLine(date, c.next_date)
  return CUT_SEVERAL
}

/** The same line on a Changes row, from the change it shows. */
export function auditPendingLine(item: AuditItem): string {
  const dismissed = item.tool === 'dismiss_commitment'
  if (item.keep_kind !== 'expense_cut') return dismissed ? KEEP_DISMISSED_TEXT : KEEP_PENDING_TEXT
  if (dismissed) return CUT_DISMISSED
  const [only, ...rest] = item.changes.filter((c) => c.field !== 'label')
  if (only && rest.length === 0 && only.before !== null && only.after !== null) {
    if (only.field === 'amount') return loweredLine(String(only.before), String(only.after))
    if (only.field === 'next_date') return movedLine(String(only.before), String(only.after))
  }
  // Anything else gets the generic line on purpose: a card link (it changes
  // how a bill counts with its card, not an amount or a date), a cadence
  // change, a planned-expense removal, or several fields at once.
  return CUT_SEVERAL
}

/** Whether keeping it moves safe to spend (an expense cut, or an income dismissal) rather than savable. */
export const keepMovesSafeToSpend = (kind: string | null | undefined, dismissed: boolean) =>
  kind === 'expense_cut' || dismissed

export const keepToast = (label: string, dismissed = false) =>
  dismissed ? `Kept “${label}”. Your safe to spend now reflects it.` : `Kept “${label}”. It now counts in your savable.`

/** The line under savable (KP10), or null when nothing is held back. */
export function savableNote(total: number | string | undefined): string | null {
  const amount = Number(total ?? 0)
  if (!(amount > 0)) return null
  return `${gbp(amount)} of income Claude added isn't counted in savable until you keep it.`
}

/** The line under safe to spend (KP19), or null when nothing is held back. */
export function safeToSpendNote(total: number | string | undefined): string | null {
  const amount = Number(total ?? 0)
  if (!(amount > 0)) return null
  return `${gbp(amount)} of bills Claude removed or reduced is still counted in your safe to spend until you keep it.`
}

/** Whether a commitment row shows the pending line, Keep and Undo (KP1, KP13, KP15, KP20). */
export function canKeep(c: Commitment): boolean {
  const held = c.direction === 'income' || c.keep_kind === 'expense_cut'
  return held && c.keep === 'pending' && (c.keep_audit_ids?.length ?? 0) > 0
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
 * made that is still pending keep is listed (9.3). An income one is not
 * added: savable already leaves it out; only the payday it sets is held. An
 * expense one still counts in safe to spend, so it is added (KP15).
 */
export const countsInListTotal = (c: Commitment) => c.status !== 'dismissed' || c.keep_kind === 'expense_cut'
