import { useCallback, useEffect, useRef, useState } from 'react'
import BudgetsView from './BudgetsView'
import SuggestSheet, { type SuggestSheetProps } from './SuggestSheet'
import ManageSheet from './ManageSheet'
import BudgetsSegment, { type BudgetsPeriod } from './BudgetsSegment'
import HistoryView from './HistoryView'
import { useToast } from '../ui/Toast'
import { budgetsAPI, syncStatusAPI } from '../../services/api'
import { failureFromError, type UndoFailure } from '../../lib/changes'
import { withTimeout } from '../../lib/forecastLoad'
import { writeFailure, type Budget, type BudgetEntry, type BudgetsResponse } from '../../lib/budgets'
import { HISTORY_MAX, HISTORY_PAGE, nowSpent, type HistoryResponse } from '../../lib/budgetHistory'

/** A request that hasn't answered by then is shown as an error (or an unknown outcome for a save). */
const TIMEOUT_MS = 10_000

type Load = { status: 'loading' | 'error' | 'ready'; data: BudgetsResponse | null }
type HistoryLoad = { status: 'loading' | 'error' | 'ready'; data: HistoryResponse | null }

/** Spending > Budgets (T-09-6): loads the cycle, runs the Suggest flow, and
 *  shows Past cycles (T-09-9), loaded the first time it's opened. */
export default function BudgetsPanel({ onOpenCategory }: { onOpenCategory: (category: string) => void }) {
  const [load, setLoad] = useState<Load>({ status: 'loading', data: null })
  const [retrying, setRetrying] = useState(false)
  const [stale, setStale] = useState<{ name: string; last_synced_at: string }[]>([])
  const [suggest, setSuggest] = useState<SuggestSheetProps['load'] | null>(null)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<UndoFailure | null>(null)
  const [managing, setManaging] = useState(false)
  const [categories, setCategories] = useState<string[]>([])
  const [manageMessage, setManageMessage] = useState<string | null>(null)
  const [period, setPeriod] = useState<BudgetsPeriod>('cycle')
  const [history, setHistory] = useState<HistoryLoad | null>(null)
  const [historyRetrying, setHistoryRetrying] = useState(false)
  const [more, setMore] = useState<'idle' | 'loading' | 'error'>('idle')
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

  const fetchHistory = async () => {
    try {
      const res = await withTimeout(budgetsAPI.history(HISTORY_PAGE), TIMEOUT_MS)
      if (mounted.current) setHistory({ status: 'ready', data: res.data })
    } catch {
      if (mounted.current) setHistory({ status: 'error', data: null })
    }
  }

  const choosePeriod = (next: BudgetsPeriod) => {
    setPeriod(next)
    if (next === 'past' && history === null) {
      setHistory({ status: 'loading', data: null })
      fetchHistory()
    }
  }

  const retryHistory = async () => {
    setHistoryRetrying(true)
    await fetchHistory()
    if (mounted.current) setHistoryRetrying(false)
  }

  /** BH10/BH14: the whole 12 again from the server, so every count stays its own. */
  const showMoreCycles = async () => {
    setMore('loading')
    try {
      const res = await withTimeout(budgetsAPI.history(HISTORY_MAX), TIMEOUT_MS)
      if (!mounted.current) return
      setHistory({ status: 'ready', data: res.data })
      setMore('idle')
      // The button is gone at the cap: keep focus in the list it opened (ux on #165).
      requestAnimationFrame(() => document.getElementById('history-by-budget')?.focus())
    } catch {
      if (mounted.current) setMore('error') // the loaded cycles stay
    }
  }

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
      // The sheet's opener may be gone (the empty state): land on the list (BM18).
      requestAnimationFrame(() => document.getElementById('budgets-heading')?.focus())
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

  const openManage = () => {
    setManageMessage(null)
    setManaging(true)
    // The categories a new budget may use: purchase categories, not commitment-covered (#156).
    budgetsAPI
      .listWithCategories()
      .then((res) => mounted.current && setCategories(res.data.budgetable_categories ?? []))
      .catch(() => {}) // Add budget just offers nothing new
  }

  /** One Manage write: the API, then the server's list, then the toast. Never optimistic. */
  const write = async (category: string, request: () => Promise<unknown>) => {
    setManageMessage(null)
    try {
      await withTimeout(request(), TIMEOUT_MS)
    } catch (err) {
      if (!mounted.current) throw err
      const message = writeFailure(err, category)
      setManageMessage(message)
      // No answer: it may have been saved, so show the server's state (BM11).
      await fetchBudgets()
      throw err
    }
    await fetchBudgets()
    if (mounted.current) toast('Budgets saved.')
  }

  return (
    <>
      {managing && load.data && (
        <ManageSheet
          data={load.data}
          categories={categories}
          message={manageMessage}
          onClose={() => setManaging(false)}
          onAdd={(category, limit) => write(category, () => budgetsAPI.create({ category, limit_pounds: limit }))}
          onSaveLimit={(b: Budget, limit) => write(b.category, () => budgetsAPI.update(b.id, { limit_pounds: limit }))}
          onTogglePause={(b: Budget) => write(b.category, () => budgetsAPI.update(b.id, { paused: !b.paused }))}
          onRemove={(b: Budget) => write(b.category, () => budgetsAPI.remove(b.id))}
          onSaveAll={(entries) => write('', () => budgetsAPI.saveAll(entries))}
          onSuggest={() => withTimeout(budgetsAPI.suggest(), TIMEOUT_MS).then((res) => res.data)}
        />
      )}
      <BudgetsSegment value={period} onChange={choosePeriod} />
      {period === 'past' ? (
        <HistoryView
          status={history?.status ?? 'loading'}
          data={history?.data ?? null}
          now={load.data ? { start: load.data.cycle.start, end: load.data.cycle.end, spent: nowSpent(load.data.budgets) } : null}
          more={more}
          retrying={historyRetrying}
          onRetry={retryHistory}
          onShowMore={showMoreCycles}
        />
      ) : (
        <BudgetsView
          status={load.status}
          data={load.data}
          staleAccounts={stale}
          retrying={retrying}
          onRetry={retry}
          onSuggest={openSuggest}
          onManage={openManage}
          onOpenCategory={onOpenCategory}
        />
      )}
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
