import { describe, expect, it } from 'vitest'
import {
  auditPendingLine,
  canKeep,
  countsInListTotal,
  keepToast,
  pendingLine,
  postEach,
  safeToSpendNote,
  savableNote,
  KEEP_PENDING_TEXT,
} from './keep'
import { item } from './changes.fixtures'
import { failureFromError } from './changes'
import type { Commitment } from '../types'

// "Keep this change" (ux spec section 9: KP1, KP3, KP10, KP13, KP15-KP20).
const commitment = (over: Partial<Commitment> = {}): Commitment => ({
  id: 'c1',
  direction: 'income',
  label: 'Salary',
  amount: 1500,
  cadence: 'monthly',
  interval_days: null,
  interval_months: null,
  next_date: '2026-10-28',
  source: 'manual',
  status: 'confirmed',
  account_id: null,
  match_key: null,
  keep: 'pending',
  keep_audit_ids: ['a1'],
  ...over,
})

describe('keep copy', () => {
  it('uses the spec sentences', () => {
    expect(KEEP_PENDING_TEXT).toBe('Not counted in savable until you keep it.')
    expect(keepToast('Salary')).toBe('Kept “Salary”. It now counts in your savable.')
  })

  it('9.3: a kept change that moves safe to spend has its own toast', () => {
    expect(keepToast('Salary', true)).toBe('Kept “Salary”. Your safe to spend now reflects it.')
  })

  it('KP10: the savable note shows the total as money, and only above zero', () => {
    expect(savableNote('500.00')).toBe("£500.00 of income Claude added isn't counted in savable until you keep it.")
    expect(savableNote('0')).toBeNull()
    expect(savableNote(undefined)).toBeNull()
  })

  it('KP19: the safe-to-spend note, only above zero', () => {
    expect(safeToSpendNote('42.50')).toBe(
      '£42.50 of bills Claude removed or reduced is still counted in your safe to spend until you keep it.',
    )
    expect(safeToSpendNote('0.00')).toBeNull()
    expect(safeToSpendNote(undefined)).toBeNull()
  })
})

const expense = (over: Partial<Commitment> = {}) =>
  commitment({ direction: 'expense', label: 'Gym', amount: 30, keep_kind: 'expense_cut', ...over })

describe('pendingLine (the commitment row, 9.2)', () => {
  it('income: raised or confirmed, and dismissed', () => {
    expect(pendingLine(commitment({ keep_kind: 'income' }))).toBe(KEEP_PENDING_TEXT)
    expect(pendingLine(commitment({ keep_kind: 'income', status: 'dismissed' }))).toBe(
      'Claude dismissed this. Your safe to spend still uses it to find your payday until you keep this change. It no longer counts in savable.',
    )
  })

  it('KP15: a dismissed expense', () => {
    expect(pendingLine(expense({ status: 'dismissed' }))).toBe(
      'Claude dismissed this. It still counts in your safe to spend until you keep this change.',
    )
  })

  it('KP18: lowered, moved later, or several changes', () => {
    expect(pendingLine(expense({ held_amount: '50.00' }))).toBe(
      'Claude lowered this from £50.00 to £30.00. It still counts at £50.00 in your safe to spend until you keep this change.',
    )
    expect(pendingLine(expense({ next_date: '2026-10-28', held_next_date: '2026-10-14' }))).toBe(
      'Claude moved this from 14 Oct to 28 Oct. It still counts on 14 Oct in your safe to spend until you keep this change.',
    )
    const generic = 'Still counted in your safe to spend until you keep this change.'
    expect(pendingLine(expense({ held_amount: '50.00', held_next_date: '2026-10-14' }))).toBe(generic)
    expect(pendingLine(expense())).toBe(generic) // a held cadence change has no held_* field
  })
})

describe('auditPendingLine (the Changes row)', () => {
  const cut = (changes: { field: string; before: string; after: string }[], over = {}) =>
    item({ keep: 'pending', keep_kind: 'expense_cut', target_label: 'Gym', changes, ...over })

  it('income keeps its lines', () => {
    expect(auditPendingLine(item({ keep: 'pending', keep_kind: 'income' }))).toBe(KEEP_PENDING_TEXT)
  })

  it('KP18: lowered, moved and several, from the change itself', () => {
    expect(auditPendingLine(cut([{ field: 'amount', before: '50.00', after: '30.00' }]))).toBe(
      'Claude lowered this from £50.00 to £30.00. It still counts at £50.00 in your safe to spend until you keep this change.',
    )
    expect(auditPendingLine(cut([{ field: 'next_date', before: '2026-10-14', after: '2026-10-28' }]))).toBe(
      'Claude moved this from 14 Oct to 28 Oct. It still counts on 14 Oct in your safe to spend until you keep this change.',
    )
    expect(auditPendingLine(cut([{ field: 'cadence', before: 'monthly', after: 'every_n_months' }]))).toBe(
      'Still counted in your safe to spend until you keep this change.',
    )
  })

  it('eng-b T-08-21b: a held card link and a held planned-expense removal get the generic line', () => {
    const generic = 'Still counted in your safe to spend until you keep this change.'
    expect(auditPendingLine(cut([{ field: 'card_account_id', before: 'k1', after: 'k2' }]))).toBe(generic)
    expect(
      auditPendingLine(
        cut(
          [
            { field: 'active', before: 'true', after: 'false' },
            { field: 'amount', before: '20.00', after: '20.00' },
          ],
          { tool: 'remove_planned_event', target_kind: 'planned_event' },
        ),
      ),
    ).toBe(generic)
  })

  it('KP15: a dismissed expense', () => {
    expect(auditPendingLine(cut([{ field: 'status', before: 'confirmed', after: 'dismissed' }], { tool: 'dismiss_commitment' }))).toBe(
      'Claude dismissed this. It still counts in your safe to spend until you keep this change.',
    )
  })
})

describe('canKeep (KP1, KP13)', () => {
  it('a pending income with rows to keep', () => {
    expect(canKeep(commitment())).toBe(true)
  })

  it('9.3: a dismissed income still pending keep', () => {
    expect(canKeep(commitment({ status: 'dismissed' }))).toBe(true)
  })

  it('not once kept, when nothing is held, or with nothing to post', () => {
    expect(canKeep(commitment({ keep: 'kept' }))).toBe(false)
    expect(canKeep(commitment({ keep: null }))).toBe(false)
    expect(canKeep(commitment({ keep_audit_ids: [] }))).toBe(false)
  })

  it('KP15/KP18: an expense cut Claude made, pending', () => {
    expect(canKeep(expense())).toBe(true)
  })

  it('KP20: an expense whose keep is null (Claude raised or confirmed it)', () => {
    expect(canKeep(expense({ keep: null, keep_kind: null }))).toBe(false)
  })
})

describe('postEach (keep oldest first, undo newest first)', () => {
  const ok = () => Promise.resolve()
  const status = (s: number) => Promise.reject({ response: { status: s } })

  it('keeps every row, oldest first', async () => {
    const posted: string[] = []
    await postEach(['a1', 'a2'], (id) => {
      posted.push(id)
      return ok()
    })
    expect(posted).toEqual(['a1', 'a2'])
  })

  it('KP5/KP7: a refused first row passes its status through (nothing was kept)', async () => {
    const err = await postEach(['a1', 'a2'], () => status(409)).catch((e) => e)
    expect(failureFromError(err)).toBe('changed')
  })

  it('KP6: a refusal after a row went through is an unknown outcome, never "nothing was changed"', async () => {
    const err = await postEach(['a1', 'a2'], (id) => (id === 'a1' ? ok() : status(500))).catch((e) => e)
    expect(failureFromError(err)).toBe('unknown')
  })
})

describe('countsInListTotal', () => {
  it('a held dismissal is listed but left out of the total, as savable leaves it out', () => {
    expect(countsInListTotal(commitment({ status: 'dismissed' }))).toBe(false)
    expect(countsInListTotal(commitment())).toBe(true)
  })

  it('KP15: a held expense dismissal still counts in safe to spend, so it stays in the total', () => {
    expect(countsInListTotal(expense({ status: 'dismissed' }))).toBe(true)
  })
})
