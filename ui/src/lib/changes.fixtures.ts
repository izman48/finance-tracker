import type { AuditItem } from './changes'

/** Audit rows shaped like GET /audit items, for the changes screen tests. */
export function item(over: Partial<AuditItem> = {}): AuditItem {
  return {
    id: 'a1',
    created_at: '2026-10-12T14:32:00Z',
    tool: 'update_commitment',
    batch_id: null,
    client_name: 'Claude Desktop',
    connection_created_at: '2026-10-03T09:00:00Z',
    target_kind: 'commitment',
    target_id: 't1',
    target_label: 'Streaming',
    changes: [{ field: 'amount', before: '10.99', after: '12.99' }],
    undone_at: null,
    ...over,
  }
}

export const addEvent = (direction: 'income' | 'expense', over: Partial<AuditItem> = {}) =>
  item({
    tool: 'add_planned_event',
    target_kind: 'planned_event',
    target_label: 'Refund',
    changes: [
      { field: 'name', before: null, after: 'Refund' },
      { field: 'direction', before: null, after: direction },
      { field: 'amount', before: null, after: '1203.00' },
      { field: 'start_date', before: null, after: '2026-11-03' },
      { field: 'active', before: null, after: true },
    ],
    ...over,
  })
