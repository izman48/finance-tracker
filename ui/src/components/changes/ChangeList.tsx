import type { ReactNode } from 'react'
import { groupBatches, type AuditItem } from '../../lib/changes'
import ChangeRow from './ChangeRow'

type Props = {
  items: AuditItem[]
  accountNames: Record<string, string>
  /** Per-row control and inline message (the Undo flow), if any. */
  renderAction?: (item: AuditItem) => ReactNode
  renderNotice?: (item: AuditItem) => ReactNode
  highlightedId?: string | null
}

/** The changes, newest first; steps of one change (same batch) grouped under a header (ux spec 1.3). */
export default function ChangeList({ items, accountNames, renderAction, renderNotice, highlightedId }: Props) {
  const row = (it: AuditItem) => (
    <ChangeRow
      key={it.id}
      item={it}
      accountNames={accountNames}
      action={renderAction?.(it)}
      notice={renderNotice?.(it)}
      highlighted={it.id === highlightedId}
    />
  )
  return (
    <ul aria-label="Changes made by Claude" className="divide-y divide-white/[0.06]">
      {groupBatches(items).map((group) =>
        group.batch ? (
          <li key={`batch-${group.items[0].id}`} className="py-4 first:pt-0 last:pb-0">
            <p className="text-xs uppercase tracking-wider text-slate-400">
              One change, {group.items.length} steps
            </p>
            {group.items.some((it) => it.undone_at === null) && (
              <p className="text-xs text-slate-400 mt-1">Undoing only one step leaves the rest in place.</p>
            )}
            <ul className="mt-3 space-y-4">{group.items.map(row)}</ul>
          </li>
        ) : (
          row(group.items[0])
        ),
      )}
    </ul>
  )
}
