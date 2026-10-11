import { describe, expect, it } from 'vitest'
import { canKeep, keepAll, keepToast, savableNote, KEEP_PENDING_TEXT } from './keep'
import { failureFromError } from './changes'
import type { Commitment } from '../types'

// "Keep this change", income scope (ux spec section 9, KP1, KP3, KP10, KP13).
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

  it('KP10: the savable note shows the total as money, and only above zero', () => {
    expect(savableNote('500.00')).toBe("£500.00 of income Claude added isn't counted in savable until you keep it.")
    expect(savableNote('0')).toBeNull()
    expect(savableNote(undefined)).toBeNull()
  })
})

describe('canKeep (KP1, KP13)', () => {
  it('a pending income with rows to keep', () => {
    expect(canKeep(commitment())).toBe(true)
  })

  it('not once kept, when nothing is held, or with nothing to post', () => {
    expect(canKeep(commitment({ keep: 'kept' }))).toBe(false)
    expect(canKeep(commitment({ keep: null }))).toBe(false)
    expect(canKeep(commitment({ keep_audit_ids: [] }))).toBe(false)
  })

  it('never on an expense, whatever the API sends (expense keep waits on D5)', () => {
    expect(canKeep(commitment({ direction: 'expense' }))).toBe(false)
  })
})

describe('keepAll', () => {
  const ok = () => Promise.resolve()
  const status = (s: number) => Promise.reject({ response: { status: s } })

  it('keeps every row, oldest first', async () => {
    const posted: string[] = []
    await keepAll(['a1', 'a2'], (id) => {
      posted.push(id)
      return ok()
    })
    expect(posted).toEqual(['a1', 'a2'])
  })

  it('KP5/KP7: a refused first row passes its status through (nothing was kept)', async () => {
    const err = await keepAll(['a1', 'a2'], () => status(409)).catch((e) => e)
    expect(failureFromError(err)).toBe('changed')
  })

  it('KP6: a refusal after a row was kept is an unknown outcome, never "nothing was changed"', async () => {
    const err = await keepAll(['a1', 'a2'], (id) => (id === 'a1' ? ok() : status(500))).catch((e) => e)
    expect(failureFromError(err)).toBe('unknown')
  })
})
