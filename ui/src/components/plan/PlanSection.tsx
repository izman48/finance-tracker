import { useCallback, useEffect, useRef, useState } from 'react'
import PlanView, { type PlanViewProps } from './PlanView'
import { planAPI } from '../../services/api'
import { withTimeout } from '../../lib/forecastLoad'

const TIMEOUT_MS = 10_000

/** Loads Plan on its own, so a failed or rate-limited /plan shows only this
 *  card's error state; safe to spend and the forecast load separately. */
export default function PlanSection() {
  const [load, setLoad] = useState<Pick<PlanViewProps, 'status' | 'data'>>({ status: 'loading', data: null })
  const mounted = useRef(true)

  const fetchPlan = useCallback(async () => {
    setLoad((l) => ({ status: 'loading', data: l.data }))
    try {
      const res = await withTimeout(planAPI.get(), TIMEOUT_MS)
      if (mounted.current) setLoad({ status: 'ready', data: res.data })
    } catch {
      // Only the spec's sentence is shown, never the error.
      if (mounted.current) setLoad({ status: 'error', data: null })
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    fetchPlan()
    return () => {
      mounted.current = false
    }
  }, [fetchPlan])

  return <PlanView {...load} onRetry={fetchPlan} />
}

/** "See your month in Plan": jumps to the Plan card and moves focus to its heading. */
export function PlanLink() {
  return (
    <a
      href="#plan"
      className="btn-link !text-xs inline-flex items-center min-h-[44px] lg:min-h-[24px]"
      onClick={(e) => {
        const heading = document.getElementById('plan-heading')
        if (!heading) return
        e.preventDefault()
        heading.focus()
      }}
    >
      See your month in Plan ↓
    </a>
  )
}
