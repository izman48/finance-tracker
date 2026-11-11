import { useEffect, useRef, useState } from 'react'
import { auditAPI } from '../services/api'
import { failureFromError, undoToast, type AuditItem, type UndoState } from '../lib/changes'
import { dateDayMonth, gbp } from '../lib/format'
import { nextUndoAfter } from '../lib/paidBack'
import type { PaidBackMark, Transaction } from '../types'
import ClaudeMarker from './changes/ClaudeMarker'
import { UndoButton, UndoNotice } from './changes/UndoControls'
import { useToast } from './ui/Toast'

const pounds = (v: number | string | null | undefined) => gbp(Number(v ?? 0))

/** The audit row an Undo acts on, as the Changes page would show it. */
const auditItem = (m: PaidBackMark): AuditItem => ({
  id: m.audit_id as string, created_at: '', tool: 'mark_paid_back', batch_id: null, client_name: null,
  connection_created_at: null, target_kind: 'repayment_mark', target_id: m.mark_id, target_label: m.label,
  changes: [], undone_at: null,
})

/** "£60.00 for Pizza Express, 6 Nov" on a credit, "£60.00 from Sam, 8 Nov" on a spend. */
function rowText(m: PaidBackMark, onSpend: boolean, withDate = true): string {
  const amount = pounds(m.amount)
  if (!onSpend && m.spend_id === null && m.against) return `${amount} against ${m.against}`
  const who = onSpend ? m.payer : m.against
  const day = onSpend ? m.credit_date : m.spend_date
  if (!who) return `${amount}: ${m.label}`
  return `${amount} ${onSpend ? 'from' : 'for'} ${who}${withDate && day ? `, ${dateDayMonth(day)}` : ''}`
}

/** The row without its date: for the Undo's accessible name (AC-35) and a mark that isn't applied. */
const shortText = (m: PaidBackMark, onSpend: boolean) => rowText(m, onSpend, false)


/** Set to a transfer by the user or a rule, or detected as one (and not set back). */
const isTransfer = (t: Transaction) =>
  t.counts_as_override === 'transfer' || (!t.counts_as_override && t.excluded_reason === 'internal_transfer')

export type PaidBackViewProps = {
  transaction: Transaction
  undo: Record<string, UndoState>
  onUndo: (mark: PaidBackMark) => void
}

/**
 * The transaction sheet's "Paid back" section (T-03-6; PRD T-03-1 Screens 1
 * and 2): each mark with Claude's marker and Undo, what is left unmarked on a
 * credit, and what a spend counts as. Absent with no marks. Figures are the
 * API's; bank and Claude text renders as text only.
 */
export function PaidBackView({ transaction, undo, onUndo }: PaidBackViewProps) {
  const marks = transaction.paid_back_marks ?? []
  if (marks.length === 0) return null
  const onSpend = transaction.transaction_type !== 'credit'
  const amount = Number(transaction.amount)
  const marked = marks.reduce((t, m) => t + Number(m.amount), 0)
  return (
    <section aria-labelledby="paid-back-heading" className="rounded-xl border border-white/10 p-4 mb-3 text-sm">
      <h4 id="paid-back-heading" tabIndex={-1} className="font-medium text-slate-100 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent/60">Paid back</h4>
      {onSpend && (
        <p className="text-slate-300 mt-1">
          {pounds(transaction.paid_back_amount)} of {pounds(amount)} paid back. Counts as{' '}
          {pounds(amount - Number(transaction.paid_back_amount ?? 0))}.
        </p>
      )}
      {!onSpend && isTransfer(transaction) && (
        <p className="text-slate-400 mt-1">Counted as a transfer, and also marked paid back.</p>
      )}
      <ul className="mt-2 space-y-2">
        {marks.map((m) => {
          const state = undo[m.mark_id] ?? { undoing: false, failure: null }
          return (
            <li key={m.mark_id}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1 text-slate-200">
                  {m.applied
                    ? rowText(m, onSpend)
                    : `${shortText(m, onSpend)}. Not applied: that purchase is not counted as spending.`}
                </span>
                {m.audit_id && <ClaudeMarker auditId={m.audit_id} />}
                {m.audit_id && (
                  <UndoButton item={auditItem(m)} state={state} onUndo={() => onUndo(m)} name={`mark ${shortText(m, onSpend)}`} />
                )}
              </div>
              {onSpend && m.cycle_closed && (
                <p className="text-xs text-slate-400">Cycle closed: its budget result was not changed.</p>
              )}
              {m.audit_id && <UndoNotice item={auditItem(m)} failure={state.failure} />}
            </li>
          )
        })}
      </ul>
      {!onSpend && (
        <p className="text-xs text-slate-400 mt-2">
          {marked >= amount
            ? 'All of this payment is marked paid back.'
            : `${pounds(amount - marked)} of ${pounds(amount)} not marked.`}
        </p>
      )}
    </section>
  )
}

/** The section with its undo wired: Undo removes the mark, the sheet refetches, focus never jumps to the page top. */
export default function PaidBackSection({ transaction, onChanged, fallbackFocus }: {
  transaction: Transaction
  onChanged: () => void
  /** Focus something that stays (the sheet's title) when the section empties. */
  fallbackFocus: () => void
}) {
  const showToast = useToast()
  const [undo, setUndo] = useState<Record<string, UndoState>>({})
  // Marks undone here: a local mirror until the page refetches (as the sheet's counts-as mirror).
  const [removed, setRemoved] = useState<PaidBackMark[]>([])
  const root = useRef<HTMLDivElement>(null)
  // Where focus goes once the undo's render lands: an Undo or alert by id, or the fallback (AC-34).
  const pendingFocus = useRef<{ undo?: string | null; alert?: string } | null>(null)
  useEffect(() => {
    const want = pendingFocus.current
    if (!want) return
    pendingFocus.current = null
    const q = (sel: string) => root.current?.querySelector<HTMLElement>(sel) ?? null
    const target = want.alert
      ? q(`button[data-undo="${want.alert}"]`) ?? q(`#change-${want.alert}-alert`)
      : (want.undo ? q(`button[data-undo="${want.undo}"]`) : null) ?? q('#paid-back-heading')
    if (target) target.focus()
    else fallbackFocus()
  })
  const gone = new Set(removed.map((m) => m.mark_id))
  const shown: Transaction = {
    ...transaction,
    paid_back_marks: (transaction.paid_back_marks ?? []).filter((m) => !gone.has(m.mark_id)),
    paid_back_amount: transaction.paid_back_amount == null ? transaction.paid_back_amount
      : Number(transaction.paid_back_amount) - removed.filter((m) => m.applied).reduce((t, m) => t + Number(m.amount), 0),
  }
  const onUndo = async (m: PaidBackMark) => {
    setUndo((u) => ({ ...u, [m.mark_id]: { undoing: true, failure: null } }))
    try {
      await auditAPI.undo(m.audit_id as string)
      const ids = (shown.paid_back_marks ?? []).flatMap((x) => (x.audit_id ? [x.audit_id] : []))
      pendingFocus.current = { undo: nextUndoAfter(ids, m.audit_id as string) }
      setRemoved((r) => [...r, m])
      showToast(undoToast(auditItem(m)))
      onChanged()
    } catch (err) {
      // Keep focus on the row: its "Try again", or the alert when it can't be retried.
      pendingFocus.current = { alert: m.audit_id as string }
      setUndo((u) => ({ ...u, [m.mark_id]: { undoing: false, failure: failureFromError(err) } }))
    }
  }
  return (
    <div ref={root}>
      <PaidBackView transaction={shown} undo={undo} onUndo={onUndo} />
    </div>
  )
}
