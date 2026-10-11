import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeepState } from '../components/changes/KeepControls'
import { useToast } from '../components/ui/Toast'
import { failureFromError } from '../lib/changes'

const IDLE: KeepState = { keeping: false, failure: null }

type Done = {
  /** The toast once the server confirms (never before: KP4). */
  toast: string
  /** Focus after success (the row), and after a 409 (its message). */
  focusId: string
  alertId: string
}

/**
 * Keep and Undo on a row (ux spec 9.4): busy while the request runs, the
 * failure kind from the HTTP status only, then a refetch so the row shows
 * the server's state. Other failures give focus back to the button
 * (`data-action={key}`), which was disabled while busy.
 */
export function useRowActions(refetch: () => Promise<unknown>) {
  const [states, setStates] = useState<Record<string, KeepState>>({})
  const mounted = useRef(true)
  const toast = useToast()

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const stateOf = useCallback((key: string) => states[key] ?? IDLE, [states])

  const run = async (key: string, request: () => Promise<unknown>, done: Done) => {
    setStates((s) => ({ ...s, [key]: { keeping: true, failure: null } }))
    let ok = false
    let failure: KeepState['failure'] = null
    try {
      await request()
      ok = true
    } catch (err) {
      failure = failureFromError(err)
    }
    if (!mounted.current) return
    setStates((s) => ({ ...s, [key]: { keeping: false, failure } }))
    if (ok) toast(done.toast)
    await refetch()
    if (!mounted.current) return
    const target = ok ? done.focusId : failure === 'changed' ? done.alertId : null
    requestAnimationFrame(() => {
      const el = target
        ? document.getElementById(target)
        : document.querySelector<HTMLElement>(`[data-action="${CSS.escape(key)}"]`)
      el?.focus()
    })
  }

  return { stateOf, run }
}
