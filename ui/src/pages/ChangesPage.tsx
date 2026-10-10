import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import ChangesView from '../components/changes/ChangesView'
import { UndoButton, UndoNotice, type UndoState } from '../components/changes/UndoControls'
import { useToast } from '../components/ui/Toast'
import { auditAPI, bankingAPI } from '../services/api'
import { failureFromError, mergeFirstPage, undoToast, type AuditItem } from '../lib/changes'
import { withTimeout } from '../lib/forecastLoad'

/** A load that hasn't answered by then is shown as the error state (ux A6). */
const AUDIT_TIMEOUT_MS = 10_000

/** "Changes made by Claude" (T-08-5): the trail of Claude's planning writes. */
export default function ChangesPage() {
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>('loading')
  const [retrying, setRetrying] = useState(false)
  const [items, setItems] = useState<AuditItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [older, setOlder] = useState<'idle' | 'loading' | 'error'>('idle')
  const [accountNames, setAccountNames] = useState<Record<string, string>>({})
  const [focusFirst, setFocusFirst] = useState(false)
  const [undo, setUndo] = useState<Record<string, UndoState>>({})
  // An element to focus once the next render has it (after an undo or a retry).
  const [focusId, setFocusId] = useState<string | null>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const mounted = useRef(true)
  const toast = useToast()
  const { hash } = useLocation()
  const target = hash.startsWith('#change-') ? hash.slice('#change-'.length) : null

  const loadFirst = useCallback(async () => {
    try {
      const res = await withTimeout(auditAPI.list(), AUDIT_TIMEOUT_MS)
      if (!mounted.current) return false
      setItems(res.data.items)
      setCursor(res.data.next_cursor)
      setStatus('ready')
      return true
    } catch {
      // Only the spec's sentence is shown, never the error itself.
      if (mounted.current) setStatus('error')
      return false
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    headingRef.current?.focus()
    loadFirst()
    // Card links show the account's name; without the list they read "A card".
    bankingAPI
      .getAccounts()
      .then((res) => {
        if (!mounted.current) return
        const accounts = res.data as { id: string; display_name: string }[]
        setAccountNames(Object.fromEntries(accounts.map((a) => [a.id, a.display_name])))
      })
      .catch(() => {})
    return () => {
      mounted.current = false
    }
  }, [loadFirst])

  // After a successful retry, focus the first row or the empty-state heading.
  useEffect(() => {
    if (!focusFirst || status !== 'ready') return
    setFocusFirst(false)
    setFocusId(items.length ? `change-${items[0].id}` : 'changes-empty')
  }, [focusFirst, status, items])

  // A "Changed by Claude" marker links to /changes#change-{id}: focus that row
  // once, when it first appears (M2). Later refetches must not pull focus back.
  const hashFocused = useRef(false)
  useEffect(() => {
    if (hashFocused.current || status !== 'ready' || !target) return
    if (!items.some((it) => it.id === target)) return
    hashFocused.current = true
    setFocusId(`change-${target}`)
  }, [status, target, items])

  useEffect(() => {
    if (!focusId) return
    document.getElementById(focusId)?.focus()
    setFocusId(null)
  }, [focusId, undo, items])

  const refetchFirst = async () => {
    try {
      const res = await withTimeout(auditAPI.list(), AUDIT_TIMEOUT_MS)
      if (mounted.current) setItems((prev) => mergeFirstPage(prev, res.data.items))
    } catch {
      // The row already shows the server's answer; a failed refresh changes nothing.
    }
  }

  const undoChange = async (it: AuditItem) => {
    setUndo((s) => ({ ...s, [it.id]: { undoing: true, failure: null } }))
    try {
      const res = await withTimeout(auditAPI.undo(it.id), AUDIT_TIMEOUT_MS)
      if (!mounted.current) return
      // The server's updated row, never an optimistic one (C7).
      setItems((prev) => prev.map((row) => (row.id === it.id ? res.data : row)))
      setUndo((s) => ({ ...s, [it.id]: { undoing: false, failure: null } }))
      toast(undoToast(it))
      setFocusId(`change-${it.id}`)
      refetchFirst()
    } catch (err) {
      if (!mounted.current) return
      const failure = failureFromError(err)
      setUndo((s) => ({ ...s, [it.id]: { undoing: false, failure } }))
      // Always show the server's real state: after a timeout the undo may
      // have gone through, and the refetch then shows the row as Undone.
      refetchFirst()
      if (failure === 'changed') {
        setFocusId(`change-${it.id}-alert`)
      } else {
        setFocusId(null)
        // The button was disabled while pending; give focus back to it.
        requestAnimationFrame(() =>
          document.querySelector<HTMLButtonElement>(`[data-undo="${CSS.escape(it.id)}"]`)?.focus(),
        )
      }
    }
  }

  const stateOf = (it: AuditItem): UndoState => undo[it.id] ?? { undoing: false, failure: null }

  const retry = async () => {
    setRetrying(true)
    const ok = await loadFirst()
    if (!mounted.current) return
    setRetrying(false)
    if (ok) setFocusFirst(true)
  }

  const loadOlder = async () => {
    if (!cursor) return
    setOlder('loading')
    try {
      const res = await withTimeout(auditAPI.list(cursor), AUDIT_TIMEOUT_MS)
      if (!mounted.current) return
      setItems((prev) => {
        const seen = new Set(prev.map((it) => it.id))
        return [...prev, ...res.data.items.filter((it) => !seen.has(it.id))]
      })
      setCursor(res.data.next_cursor)
      setOlder('idle')
    } catch {
      if (mounted.current) setOlder('error')
    }
  }

  return (
    <ChangesView
      status={status}
      items={items}
      accountNames={accountNames}
      hasOlder={cursor !== null}
      older={older}
      retrying={retrying}
      onRetry={retry}
      onOlder={loadOlder}
      headingRef={headingRef}
      highlightedId={target}
      renderAction={(it) => <UndoButton item={it} state={stateOf(it)} onUndo={undoChange} />}
      renderNotice={(it) => <UndoNotice item={it} failure={stateOf(it).failure} />}
    />
  )
}
