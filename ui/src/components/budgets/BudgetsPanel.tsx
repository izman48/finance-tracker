import { useCallback, useEffect, useRef, useState } from 'react'
import BudgetsView from './BudgetsView'
import SuggestSheet, { type SuggestSheetProps } from './SuggestSheet'
import { useToast } from '../ui/Toast'
import { budgetsAPI, syncStatusAPI } from '../../services/api'
import { failureFromError, type UndoFailure } from '../../lib/changes'
import { withTimeout } from '../../lib/forecastLoad'
import type { BudgetEntry, BudgetsResponse } from '../../lib/budgets'

/** A request that hasn't answered by then is shown as an error (or an unknown outcome for a save). */
const TIMEOUT_MS = 10_000

type Load = { status: 'loading' | 'error' | 'ready'; data: BudgetsResponse | null }

/** Spending > Budgets (T-09-6): loads the cycle, and runs the Suggest flow. */
export default function BudgetsPanel({ onOpenCategory }: { onOpenCategory: (category: string) => void }) {
  const [load, setLoad] = useState<Load>({ status: 'loading', data: null })
  const [retrying, setRetrying] = useState(false)
  const [stale, setStale] = useState<{ name: string; last_synced_at: string }[]>([])
  const [suggest, setSuggest] = useState<SuggestSheetProps['load'] | null>(null)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<UndoFailure | null>(null)
  const mounted = useRef(true)
  const toast = useToast()

  const fetchBudgets = useCallback(async () => {
    try {
      const res = await withTimeout(budgetsAPI.list(), TIMEOUT_MS)
      if (mounted.current) setLoad({ status: 'ready', data: res.data })
    } catch {
      // Only the spec's sentence is shown, never the error.
      if (mounted.current) setLoad((l) => ({ status: 'error', data: l.data }))
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    fetchBudgets()
    syncStatusAPI
      .get()
      .then((res) => {
        if (!mounted.current) return
        setStale(
          res.data.connections
            .filter((c) => c.stale && c.last_synced_at)
            .map((c) => ({ name: c.provider, last_synced_at: c.last_synced_at as string })),
        )
      })
      .catch(() => {}) // the note is a nicety; budgets still show
    return () => {
      mounted.current = false
    }
  }, [fetchBudgets])

  const retry = async () => {
    setRetrying(true)
    await fetchBudgets()
    if (mounted.current) setRetrying(false)
  }

  const loadSuggestions = async () => {
    setSuggest({ status: 'loading' })
    try {
      const res = await withTimeout(budgetsAPI.suggest(), TIMEOUT_MS)
      if (mounted.current) setSuggest({ status: 'ready', data: res.data })
    } catch {
      if (mounted.current) setSuggest({ status: 'error' })
    }
  }

  const openSuggest = () => {
    setFailure(null)
    loadSuggestions()
  }

  const save = async (budgets: BudgetEntry[]) => {
    setSaving(true)
    setFailure(null)
    try {
      const res = await withTimeout(budgetsAPI.saveAll(budgets), TIMEOUT_MS)
      if (!mounted.current) return
      setLoad({ status: 'ready', data: res.data }) // the server's list, never an optimistic one
      setSuggest(null)
      toast('Budgets set for this pay cycle.')
    } catch (err) {
      if (!mounted.current) return
      const kind = failureFromError(err)
      setFailure(kind)
      // No answer: it may have saved, so show the server's state.
      if (kind === 'unknown') fetchBudgets()
    } finally {
      if (mounted.current) setSaving(false)
    }
  }

  return (
    <>
      <BudgetsView
        status={load.status}
        data={load.data}
        staleAccounts={stale}
        retrying={retrying}
        onRetry={retry}
        onSuggest={openSuggest}
        onOpenCategory={onOpenCategory}
      />
      {suggest && (
        <SuggestSheet
          load={suggest}
          saving={saving}
          failure={failure}
          onCancel={() => setSuggest(null)}
          onRetry={loadSuggestions}
          onSave={save}
        />
      )}
    </>
  )
}
