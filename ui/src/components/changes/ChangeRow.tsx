import type { ReactNode } from 'react'
import { changeLines, changeTitle, clientText, metaTime, type AuditItem } from '../../lib/changes'
import { dateDayMonth } from '../../lib/format'

type Props = {
  item: AuditItem
  accountNames: Record<string, string>
  /** The row's control (the Undo button), placed right on desktop and full width on mobile. */
  action?: ReactNode
  /** An inline message under the change lines (an undo failure). */
  notice?: ReactNode
  /** The row a marker linked to: ringed so it stands out (M2). */
  highlighted?: boolean
}

/**
 * One change Claude made (ux spec 1.3). Every string from the API (labels,
 * names, the client name) is rendered as text: no HTML, no links built from it.
 */
export default function ChangeRow({ item, accountNames, action, notice, highlighted = false }: Props) {
  const title = changeTitle(item)
  const lines = changeLines(item, accountNames)
  const client = clientText(item.client_name)
  const undone = item.undone_at !== null
  const muted = undone ? 'text-slate-400' : ''

  return (
    <li id={`change-${item.id}`} tabIndex={-1} className={`py-4 first:pt-0 last:pb-0 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-accent/60 ${highlighted ? 'ring-2 ring-accent/60 px-2 -mx-2' : ''}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className={`font-medium [overflow-wrap:anywhere] ${undone ? 'text-slate-400' : 'text-slate-200'}`}>
            {title}
            {undone && <span className="chip ml-2 align-middle">Undone {dateDayMonth(item.undone_at)}</span>}
          </p>
          {lines.length > 0 && (
            <dl className="mt-2 space-y-1 text-sm">
              {lines.map((line) => (
                <div key={line.label} className="flex gap-3">
                  <dt className="w-28 sm:w-40 shrink-0 text-slate-400">{line.label}</dt>
                  <dd className={`min-w-0 tnum ${muted || 'text-slate-100'}`}>
                    {line.before !== undefined && (
                      <>
                        <span className="text-slate-400">{line.before}</span>
                        <span aria-hidden="true"> → </span>
                        <span className="sr-only"> changed to </span>
                      </>
                    )}
                    {line.after}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          <p className="mt-2 text-xs text-slate-400 [overflow-wrap:anywhere]">
            <time dateTime={item.created_at}>{metaTime(item.created_at)}</time>
            {' · '}
            <span title={client.title}>{client.text}</span>
            {item.connection_created_at && ` · connected ${dateDayMonth(item.connection_created_at)}`}
          </p>
          {notice}
        </div>
        {action}
      </div>
    </li>
  )
}
