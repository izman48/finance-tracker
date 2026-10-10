import type { ReactNode, Ref } from 'react'
import type { AuditItem } from '../../lib/changes'
import ChangeList from './ChangeList'

export type ChangesViewProps = {
  status: 'loading' | 'error' | 'ready'
  items: AuditItem[]
  accountNames: Record<string, string>
  hasOlder: boolean
  older: 'idle' | 'loading' | 'error'
  /** A retry of the first page is in flight (the error stays up meanwhile). */
  retrying?: boolean
  onRetry: () => void
  onOlder: () => void
  headingRef?: Ref<HTMLHeadingElement>
  renderAction?: (item: AuditItem) => ReactNode
  renderNotice?: (item: AuditItem) => ReactNode
}

const BUTTON = 'btn-ghost min-h-[44px] sm:min-h-0'

/**
 * The "Changes made by Claude" page body (ux spec 1.2 and 1.6). No state of
 * it carries a message from the server: every sentence is the spec's own.
 */
export default function ChangesView(props: ChangesViewProps) {
  const { status, items, hasOlder, older, retrying = false, onRetry, onOlder, headingRef } = props
  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
      <div>
        <h1 ref={headingRef} tabIndex={-1} className="font-display font-bold text-2xl text-slate-50 rounded focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent/60">
          Changes made by Claude
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Everything an AI assistant changed in your planned events and commitments. You can undo any change here.
        </p>
        <p className="text-xs text-slate-400 mt-1">
          &quot;via&quot; names are chosen by the app that connected. nilu. doesn&apos;t check them.
        </p>
      </div>

      {status === 'error' ? (
        <div role="alert" className="banner-err flex flex-col sm:flex-row sm:items-center gap-3">
          <p className="flex-1">Couldn&apos;t load the changes made by Claude. Nothing has been changed. Try again.</p>
          <button type="button" className={BUTTON} onClick={onRetry} disabled={retrying} aria-busy={retrying}>
            {retrying ? 'Trying…' : 'Try again'}
          </button>
        </div>
      ) : (
        <div className="card card-pad">
          {status === 'loading' ? (
            <>
              <span role="status" className="sr-only">Loading changes…</span>
              <ul aria-label="Changes made by Claude" aria-busy="true" className="space-y-4">
                {[0, 1, 2].map((i) => (
                  <li key={i} data-skeleton className="space-y-2 motion-safe:animate-pulse">
                    <div className="h-4 w-2/3 rounded bg-white/[0.06]" />
                    <div className="h-3 w-1/2 rounded bg-white/[0.04]" />
                  </li>
                ))}
              </ul>
            </>
          ) : items.length === 0 ? (
            <div className="text-center py-8">
              <h2 id="changes-empty" tabIndex={-1} className="text-slate-200 font-medium outline-none">
                Claude hasn&apos;t changed anything yet
              </h2>
              <p className="text-sm text-slate-400 mt-2 max-w-md mx-auto">
                When you let an AI assistant change your planned events or commitments, every change appears here and
                you can undo it.
              </p>
            </div>
          ) : (
            <ChangeList
              items={items}
              accountNames={props.accountNames}
              renderAction={props.renderAction}
              renderNotice={props.renderNotice}
            />
          )}
        </div>
      )}

      {status === 'ready' && hasOlder && (
        <div className="flex flex-col items-center gap-2">
          {older === 'error' && <p role="alert" className="text-sm text-neg">Couldn&apos;t load older changes. Try again.</p>}
          <button
            type="button"
            className={BUTTON}
            onClick={onOlder}
            disabled={older === 'loading'}
            aria-busy={older === 'loading'}
          >
            {older === 'error' ? 'Try again' : 'Show older changes'}
          </button>
        </div>
      )}
    </div>
  )
}
