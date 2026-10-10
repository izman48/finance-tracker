import { describe, expect, it } from 'vitest'
import {
  changeLines,
  changeTitle,
  clientText,
  groupBatches,
  mergeFirstPage,
  metaTime,
  undoFailure,
  undoToast,
} from './changes'
import { addEvent, item } from './changes.fixtures'

// ux spec nilu-s08-claude-changes.md section 1 (C-criteria), T-08-5.

describe('changeTitle (1.4)', () => {
  it('names each tool in plain words, with the label in curly quotes', () => {
    expect(changeTitle(item())).toBe('Changed the commitment “Streaming”')
    expect(changeTitle(addEvent('expense'))).toBe('Added a planned expense: “Refund”')
    expect(changeTitle(addEvent('income'))).toBe('Added expected income: “Refund”')
    expect(changeTitle(item({ tool: 'remove_planned_event', target_label: 'Trip' }))).toBe(
      'Removed a planned event: “Trip”',
    )
    expect(changeTitle(item({ tool: 'dismiss_commitment' }))).toBe('Dismissed the commitment “Streaming”')
  })

  it('an update that confirms a suggestion reads as a confirmation', () => {
    const confirm = item({ changes: [{ field: 'status', before: 'suggested', after: 'confirmed' }] })
    expect(changeTitle(confirm)).toBe('Confirmed “Streaming” as a commitment')
  })
})

describe('changeLines (C5)', () => {
  it('an update shows each changed field as before → after', () => {
    const lines = changeLines(
      item({
        changes: [
          { field: 'amount', before: '10.99', after: '12.99' },
          { field: 'next_date', before: '2026-11-03', after: '2026-12-03' },
          { field: 'cadence', before: 'monthly', after: 'weekly' },
          { field: 'label', before: 'Netflix', after: 'Streaming' },
          { field: 'card_account_id', before: null, after: 'acc-1' },
        ],
      }),
      { 'acc-1': 'Amex Gold' },
    )
    expect(lines).toEqual([
      { label: 'Amount', before: '£10.99', after: '£12.99' },
      { label: 'Next date', before: '3 Nov', after: '3 Dec' },
      { label: 'How often', before: 'Monthly', after: 'Weekly' },
      { label: 'Name', before: 'Netflix', after: 'Streaming' },
      { label: 'Card', before: 'None', after: 'Amex Gold' },
    ])
  })

  it('an add shows single values, and expected income says it is not counted', () => {
    expect(changeLines(addEvent('expense'), {})).toEqual([
      { label: 'Amount', after: '£1,203.00' },
      { label: 'Date', after: '3 Nov' },
    ])
    expect(changeLines(addEvent('income'), {})).toContainEqual({
      label: 'Counted in safe to spend',
      after: 'No, not until it arrives',
    })
  })

  it('a remove shows the amount and date it took away, as single values', () => {
    const removed = item({
      tool: 'remove_planned_event',
      target_kind: 'planned_event',
      target_label: 'Trip',
      changes: [
        { field: 'amount', before: '450.00', after: '450.00' },
        { field: 'start_date', before: '2026-12-01', after: '2026-12-01' },
        { field: 'active', before: true, after: false },
      ],
    })
    expect(changeLines(removed, {})).toEqual([
      { label: 'Amount', after: '£450.00' },
      { label: 'Date', after: '1 Dec' },
    ])
  })

  it('status values read as people say them', () => {
    expect(changeLines(item({ tool: 'dismiss_commitment', changes: [{ field: 'status', before: 'confirmed', after: 'dismissed' }] }), {}))
      .toEqual([{ label: 'Status', before: 'Active', after: 'Dismissed' }])
    expect(changeLines(item({ changes: [{ field: 'status', before: 'suggested', after: 'confirmed' }] }), {}))
      .toEqual([{ label: 'Status', before: 'Suggested', after: 'Confirmed' }])
  })

  it('an unknown card id is never shown raw', () => {
    const lines = changeLines(item({ changes: [{ field: 'card_account_id', before: 'gone', after: null }] }), {})
    expect(lines).toEqual([{ label: 'Card', before: 'A card', after: 'None' }])
  })
})

describe('clientText (C15)', () => {
  it('is plain "via" text, with a fallback for no name', () => {
    expect(clientText('Claude Desktop')).toEqual({ text: 'via Claude Desktop', title: 'Claude Desktop' })
    expect(clientText(null)).toEqual({ text: 'via an unnamed app', title: undefined })
    expect(clientText('  ')).toEqual({ text: 'via an unnamed app', title: undefined })
  })

  it('removes hidden characters before truncating to 40', () => {
    const sneaky = 'Claude‮ Desktop​'
    expect(clientText(sneaky)).toEqual({ text: 'via Claude Desktop', title: 'Claude Desktop' })
    const long = 'A'.repeat(60)
    expect(clientText(long)).toEqual({ text: `via ${'A'.repeat(40)}…`, title: long })
  })
})

describe('metaTime', () => {
  it('shows day, month and local time, and the year only when it differs', () => {
    const now = new Date('2026-10-20T12:00:00')
    expect(metaTime('2026-10-12T14:32:00', now)).toBe('12 Oct, 14:32')
    expect(metaTime('2025-10-12T14:32:00', now)).toBe('12 Oct 2025, 14:32')
  })
})

describe('groupBatches (C11)', () => {
  it('groups consecutive rows that share a batch id', () => {
    const rows = [
      item({ id: '1', batch_id: 'b' }),
      item({ id: '2', batch_id: 'b' }),
      item({ id: '3' }),
      item({ id: '4', batch_id: 'c' }),
    ]
    expect(groupBatches(rows).map((g) => g.items.map((r) => r.id))).toEqual([['1', '2'], ['3'], ['4']])
    expect(groupBatches(rows).map((g) => g.batch)).toEqual([true, false, false])
  })
})

describe('undoToast (1.5)', () => {
  it('says what the undo did, per tool', () => {
    expect(undoToast(addEvent('expense'))).toBe('Removed “Refund” from your planned events.')
    expect(undoToast(item({ tool: 'remove_planned_event', target_label: 'Trip' }))).toBe('Put “Trip” back in your planned events.')
    expect(undoToast(item())).toBe('Put “Streaming” back to how it was.')
    expect(undoToast(item({ tool: 'dismiss_commitment' }))).toBe('“Streaming” is back in your commitments.')
  })
})

describe('undoFailure (C8, C9)', () => {
  it('maps a status to the row state, never to server text', () => {
    expect(undoFailure(409)).toBe('changed')
    expect(undoFailure(429)).toBe('rate')
    expect(undoFailure(500)).toBe('other')
    expect(undoFailure(404)).toBe('other')
    expect(undoFailure(undefined)).toBe('other') // network error or timeout
  })
})

describe('mergeFirstPage (refetch after an undo)', () => {
  it('replaces the rows the first page returns and keeps older rows already loaded', () => {
    const loaded = [item({ id: '1' }), item({ id: '2' }), item({ id: '3', target_label: 'Older' })]
    const fresh = [item({ id: '1', undone_at: '2026-10-13T08:00:00Z' }), item({ id: '2' })]
    const merged = mergeFirstPage(loaded, fresh)
    expect(merged.map((r) => r.id)).toEqual(['1', '2', '3'])
    expect(merged[0].undone_at).toBe('2026-10-13T08:00:00Z')
  })
})
