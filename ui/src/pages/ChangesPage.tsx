import { useCallback, useEffect, useRef, useState } from 'react'
import ChangesView from '../components/changes/ChangesView'
import { auditAPI, bankingAPI } from '../services/api'
import type { AuditItem } from '../lib/changes'
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
  const headingRef = useRef<HTMLHeadingElement>(null)
  const mounted = useRef(true)

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
    const target = items.length ? `change-${items[0].id}` : 'changes-empty'
    document.getElementById(target)?.focus()
  }, [focusFirst, status, items])

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
    />
  )
}
