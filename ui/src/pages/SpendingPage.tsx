import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDownToLine, ChevronDown, SlidersHorizontal, X } from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { analyticsAPI, bankingAPI, TransactionQuery } from '../services/api'
import { Account, Transaction } from '../types'
import { gbp, money, dateDMY } from '../lib/format'
import MonthlySpendingChart from '../components/MonthlySpendingChart'
import TransactionDetailSheet from '../components/TransactionDetailSheet'
import AddRuleModal from '../components/AddRuleModal'
import PayOnFinanceModal from '../components/PayOnFinanceModal'
import AnimatedNumber from '../components/ui/AnimatedNumber'
import InfoTip from '../components/ui/InfoTip'
import { useToast } from '../components/ui/Toast'
import { EXPLAIN } from '../copy/statExplainers'
import useReveal from '../components/ui/useReveal'

interface CategorySlice {
  category: string
  total: number
  count: number
}
interface MerchantSlice {
  merchant: string
  total: number
}
interface Composition {
  card_repayments: number
  transfers: number
  commitments: number
  other: number
}
interface Spending {
  lens: string
  period: string
  period_start: string
  period_end: string
  total_spent: number
  charged_to_credit: number
  paid_from_cash: number
  composition: Composition | null
  by_category: CategorySlice[]
  top_merchants: MerchantSlice[]
}

type Lens = 'money_out' | 'purchases'
type SpendKind = 'spend' | 'cash' | 'credit' | 'money_out'

const MERCHANTS_DEFAULT = 10
const PAGE_SIZE = 50

const PERIODS = [
  { key: 'since_payday', label: 'Since payday' },
  { key: 'this_month', label: 'Month to date' },
  { key: 'last_30', label: 'Last 30 days' },
  { key: 'custom', label: 'Custom' },
]

const KIND_LABEL: Record<SpendKind, string> = {
  spend: 'All spending',
  cash: 'Paid from bank',
  credit: 'Charged to credit',
  money_out: 'Money out',
}

const LENS_KEY = 'insights.lens'

const longDate = (d: string) =>
  new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

const BAR_COLORS = ['#2DD4A7', '#38BDF8', '#A78BFA', '#FBBF24', '#FB7185', '#34D399', '#818CF8', '#F472B6']

const EXCLUDE_COMMITMENTS_KEY = 'insights.excludeCommitments'

export default function SpendingPage() {
  // ---- aggregates (the figures) -------------------------------------------
  const [period, setPeriod] = useState('since_payday')
  const [frm, setFrm] = useState('')
  const [to, setTo] = useState('')
  const [data, setData] = useState<Spending | null>(null)
  // A second, scoped aggregate that drives the category donut + merchant list
  // when a drill is active, so "Charged to credit" refilters the breakdown too
  // (not just the transaction list). Null → show the unscoped `data` breakdown.
  // The label travels WITH the data so the two can never disagree mid-refetch.
  const [breakdown, setBreakdown] = useState<{ data: Spending; label: string } | null>(null)
  const [prevTotal, setPrevTotal] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  // Persisted: "how am I spending the rest of my money" is a standing question.
  const [excludeCommitments, setExcludeCommitments] = useState(
    () => localStorage.getItem(EXCLUDE_COMMITMENTS_KEY) === '1',
  )
  // money_out (default): cash that actually left your bank, reconciles to a
  // statement. purchases: spend booked at purchase time.
  const [lens, setLensState] = useState<Lens>(
    () => (localStorage.getItem(LENS_KEY) === 'purchases' ? 'purchases' : 'money_out'),
  )
  const setLens = (l: Lens) => {
    localStorage.setItem(LENS_KEY, l)
    setLensState(l)
    setDrillKind(null) // a drill from the old lens no longer applies
  }

  // ---- the transaction list (server-driven; shares the figures' context) ---
  const [items, setItems] = useState<Transaction[]>([])
  const [total, setTotal] = useState(0)
  const [listLoading, setListLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [facets, setFacets] = useState<{ categories: string[]; merchants: string[] }>({
    categories: [],
    merchants: [],
  })

  // Filters. Tapping a figure above sets these — the list *is* the drill-down.
  const [drillKind, setDrillKind] = useState<SpendKind | null>(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [selectedAccount, setSelectedAccount] = useState('')
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const [selectedMerchant, setSelectedMerchant] = useState('')
  const [selectedType, setSelectedType] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [minAmount, setMinAmount] = useState('')
  const [maxAmount, setMaxAmount] = useState('')
  // Nothing is hidden by default — transfers and card repayments show,
  // labelled; the user opts in to hiding each.
  const [hideTransfers, setHideTransfers] = useState(false)
  const [hideCardPayments, setHideCardPayments] = useState(false)
  const [sortField, setSortField] = useState<'date' | 'amount'>('date')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  const [showFilters, setShowFilters] = useState(false)

  // Bulk category update (list-level; everything else lives in the row sheet).
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkCategory, setBulkCategory] = useState('')
  const [bulkMode, setBulkMode] = useState(false)
  const [bulkBusy, setBulkBusy] = useState(false)

  const [sheetTx, setSheetTx] = useState<Transaction | null>(null)
  const [ruleTx, setRuleTx] = useState<Transaction | null>(null)
  const [financeTx, setFinanceTx] = useState<Transaction | null>(null)
  const [showAllMerchants, setShowAllMerchants] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  // The breakdown (donut + merchants) tracks the drill: the cash/credit split
  // and the account picker scope it. Category/merchant/search stay list-only so
  // the donut keeps showing the full breakdown you're drilling within, and a
  // tapped slice still reconciles to the list beneath it.
  const breakdownScopeKind = drillKind === 'cash' || drillKind === 'credit' ? drillKind : undefined
  const breakdownActive = !!selectedAccount || !!breakdownScopeKind

  const listRef = useRef<HTMLDivElement>(null)
  const showToast = useToast()
  const revealRef = useReveal(!loading && !!data)

  const toggleExcludeCommitments = (on: boolean) => {
    setExcludeCommitments(on)
    localStorage.setItem(EXCLUDE_COMMITMENTS_KEY, on ? '1' : '0')
  }

  // Aggregates
  useEffect(() => {
    if (period === 'custom' && (!frm || !to)) return
    setLoading(true)
    analyticsAPI
      .getSpending(period, period === 'custom' ? frm : undefined, period === 'custom' ? to : undefined, {
        excludeCommitments,
        lens,
        hideTransfers,
        hideCardPayments,
      })
      .then((res) => {
        const d = res.data as Spending
        d.total_spent = Number(d.total_spent)
        d.charged_to_credit = Number(d.charged_to_credit)
        d.paid_from_cash = Number(d.paid_from_cash)
        if (d.composition) {
          d.composition = {
            card_repayments: Number(d.composition.card_repayments),
            transfers: Number(d.composition.transfers),
            commitments: Number(d.composition.commitments),
            other: Number(d.composition.other),
          }
        }
        d.by_category = d.by_category.map((c) => ({ ...c, total: Number(c.total) }))
        d.top_merchants = d.top_merchants.map((m) => ({ ...m, total: Number(m.total) }))
        setData(d)
      })
      .catch((e) => console.error('Failed to load spending', e))
      .finally(() => setLoading(false))
  }, [period, frm, to, excludeCommitments, lens, hideTransfers, hideCardPayments, reloadKey])

  // Scoped breakdown for the donut + merchants when a drill is active. Skipped
  // otherwise (the unscoped `data` already carries the full breakdown).
  useEffect(() => {
    if (!breakdownActive) {
      setBreakdown(null)
      return
    }
    if (period === 'custom' && (!frm || !to)) return
    let cancelled = false
    analyticsAPI
      .getSpending(period, period === 'custom' ? frm : undefined, period === 'custom' ? to : undefined, {
        excludeCommitments,
        lens,
        hideTransfers,
        hideCardPayments,
        accountId: selectedAccount || undefined,
        kind: breakdownScopeKind,
      })
      .then((res) => {
        if (cancelled) return
        const d = res.data as Spending
        d.total_spent = Number(d.total_spent)
        d.by_category = d.by_category.map((c) => ({ ...c, total: Number(c.total) }))
        d.top_merchants = d.top_merchants.map((m) => ({ ...m, total: Number(m.total) }))
        // Caption the scope this fetch represents, captured at request time so
        // it always matches `d` (never the label of a newer, pending scope).
        const acct = selectedAccount
          ? accounts.find((a) => a.id === selectedAccount)?.display_name ?? 'Unknown account'
          : null
        const label = [
          breakdownScopeKind === 'credit' ? 'on credit' : breakdownScopeKind === 'cash' ? 'from bank' : null,
          acct,
        ]
          .filter(Boolean)
          .join(' · ')
        setBreakdown({ data: d, label })
      })
      .catch((e) => !cancelled && console.error('Failed to load scoped breakdown', e))
    return () => {
      cancelled = true
    }
  }, [
    breakdownActive, breakdownScopeKind, selectedAccount, accounts, period, frm, to,
    excludeCommitments, lens, hideTransfers, hideCardPayments, reloadKey,
  ])

  // vs the previous same-length window — a "pace" signal on the headline.
  useEffect(() => {
    if (!data) {
      setPrevTotal(null)
      return
    }
    const start = new Date(data.period_start)
    const end = new Date(data.period_end)
    const lenDays = Math.max(1, Math.round((end.getTime() - start.getTime()) / 864e5) + 1)
    const prevEnd = new Date(start.getTime() - 864e5)
    const prevStart = new Date(prevEnd.getTime() - (lenDays - 1) * 864e5)
    const iso = (d: Date) => d.toISOString().slice(0, 10)
    let cancelled = false
    analyticsAPI
      .getSpending('custom', iso(prevStart), iso(prevEnd), { excludeCommitments, lens, hideTransfers, hideCardPayments })
      .then((res) => !cancelled && setPrevTotal(Number(res.data.total_spent)))
      .catch(() => !cancelled && setPrevTotal(null))
    return () => {
      cancelled = true
    }
  }, [data, excludeCommitments, lens, hideTransfers, hideCardPayments])

  // Accounts + facets (once, refreshed after edits)
  useEffect(() => {
    bankingAPI.getAccounts().then((res) => setAccounts(res.data)).catch(() => {})
    bankingAPI.getTransactionFacets().then((res) => setFacets(res.data)).catch(() => {})
  }, [reloadKey])

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search), 300)
    return () => window.clearTimeout(t)
  }, [search])

  // The list shares the figures' period unless explicit dates are set, so a
  // tapped number always equals the sum of what's listed beneath it.
  const listQuery: TransactionQuery | null = useMemo(() => {
    if (!data) return null
    return {
      page,
      page_size: PAGE_SIZE,
      account_id: selectedAccount || undefined,
      search: debouncedSearch || undefined,
      category: selectedCategories.length ? selectedCategories : undefined,
      merchant: selectedMerchant || undefined,
      type: (selectedType as TransactionQuery['type']) || undefined,
      date_from: dateFrom || data.period_start,
      date_to: dateTo || data.period_end,
      min_amount: minAmount || undefined,
      max_amount: maxAmount || undefined,
      hide_transfers: hideTransfers || undefined,
      hide_card_payments: hideCardPayments || undefined,
      exclude_commitments: excludeCommitments,
      kind: drillKind ?? undefined,
      sort: sortField,
      sort_dir: sortDirection,
    }
  }, [
    data, page, selectedAccount, debouncedSearch, selectedCategories, selectedMerchant,
    selectedType, dateFrom, dateTo, minAmount, maxAmount, hideTransfers, hideCardPayments,
    excludeCommitments, drillKind, sortField, sortDirection,
  ])

  useEffect(() => {
    setPage(1)
    setSelectedIds(new Set())
  }, [
    debouncedSearch, selectedAccount, selectedCategories, selectedMerchant, selectedType,
    dateFrom, dateTo, minAmount, maxAmount, hideTransfers, hideCardPayments, drillKind, sortField,
    sortDirection, excludeCommitments, period, frm, to,
  ])

  useEffect(() => {
    if (!listQuery) return
    let cancelled = false
    setListLoading(true)
    bankingAPI
      .getTransactions(listQuery)
      .then((res) => {
        if (cancelled) return
        setItems(res.data.items)
        setTotal(res.data.total)
      })
      .catch((e) => console.error('Failed to load transactions', e))
      .finally(() => !cancelled && setListLoading(false))
    return () => {
      cancelled = true
    }
  }, [listQuery, reloadKey])

  const reloadAll = () => setReloadKey((k) => k + 1)

  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.display_name ?? 'Unknown account'

  const scrollToList = () => listRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  const drill = (patch: {
    kind?: SpendKind | null
    category?: string
    merchant?: string
  }) => {
    if (patch.kind !== undefined) setDrillKind(patch.kind)
    if (patch.category !== undefined) setSelectedCategories(patch.category ? [patch.category] : [])
    if (patch.merchant !== undefined) setSelectedMerchant(patch.merchant)
    scrollToList()
  }

  const clearAllFilters = () => {
    setDrillKind(null)
    setSearch('')
    setSelectedAccount('')
    setSelectedCategories([])
    setSelectedMerchant('')
    setSelectedType('')
    setDateFrom('')
    setDateTo('')
    setMinAmount('')
    setMaxAmount('')
    setHideTransfers(false)
    setHideCardPayments(false)
    toggleExcludeCommitments(false)
  }

  // Visible chips so the "I tapped Groceries" state is always legible. Every
  // active filter must appear here — the reset bar, chip row and Filters
  // highlight all key off chips.length, so an omission hides a live filter.
  const chips: { key: string; label: string; onClear: () => void }[] = [
    ...(drillKind ? [{ key: 'kind', label: KIND_LABEL[drillKind], onClear: () => setDrillKind(null) }] : []),
    ...(selectedAccount ? [{ key: 'account', label: accountName(selectedAccount), onClear: () => setSelectedAccount('') }] : []),
    ...(debouncedSearch ? [{ key: 'search', label: `“${debouncedSearch}”`, onClear: () => setSearch('') }] : []),
    ...selectedCategories.map((c) => ({
      key: `cat-${c}`,
      label: c,
      onClear: () => setSelectedCategories(selectedCategories.filter((x) => x !== c)),
    })),
    ...(selectedMerchant ? [{ key: 'merchant', label: selectedMerchant, onClear: () => setSelectedMerchant('') }] : []),
    ...(selectedType ? [{ key: 'type', label: selectedType === 'debit' ? 'Expenses only' : 'Income only', onClear: () => setSelectedType('') }] : []),
    ...(dateFrom ? [{ key: 'from', label: `from ${dateFrom}`, onClear: () => setDateFrom('') }] : []),
    ...(dateTo ? [{ key: 'to', label: `to ${dateTo}`, onClear: () => setDateTo('') }] : []),
    ...(minAmount ? [{ key: 'min', label: `≥ £${minAmount}`, onClear: () => setMinAmount('') }] : []),
    ...(maxAmount ? [{ key: 'max', label: `≤ £${maxAmount}`, onClear: () => setMaxAmount('') }] : []),
    ...(hideTransfers ? [{ key: 'ht', label: 'hiding transfers', onClear: () => setHideTransfers(false) }] : []),
    ...(hideCardPayments ? [{ key: 'hcp', label: 'hiding card payments', onClear: () => setHideCardPayments(false) }] : []),
    ...(excludeCommitments ? [{ key: 'xc', label: 'excluding commitments', onClear: () => toggleExcludeCommitments(false) }] : []),
  ]

  const patchItem = (id: string, patch: Partial<Transaction>) => {
    setItems((xs) => xs.map((tx) => (tx.id === id ? { ...tx, ...patch } : tx)))
  }

  const toggleSelected = (id: string) => {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedIds(next)
  }

  const bulkApply = async () => {
    if (selectedIds.size === 0) return
    setBulkBusy(true)
    try {
      await Promise.all(
        Array.from(selectedIds).map((id) =>
          bankingAPI.updateTransaction(id, { category: bulkCategory || null }),
        ),
      )
      setBulkMode(false)
      setSelectedIds(new Set())
      setBulkCategory('')
      reloadAll()
    } catch (e) {
      console.error('Bulk update failed', e)
      showToast('Failed to update some transactions', { tone: 'err' })
    } finally {
      setBulkBusy(false)
    }
  }

  const downloadCSV = async () => {
    if (!data) return
    try {
      // A faithful, complete copy of the period — every transaction, INCLUDING
      // the rows we exclude from totals, with the derived flags that carry our
      // judgements. Deliberately ignores the on-screen category/kind/hide
      // filters so the export is auditable, not a lossy subset.
      const exportQuery: TransactionQuery = {
        date_from: data.period_start,
        date_to: data.period_end,
        include_excluded: true,
        sort: 'date',
        sort_dir: 'desc',
        page_size: 100,
      }
      const all: Transaction[] = []
      let p = 1
      for (;;) {
        const res = await bankingAPI.getTransactions({ ...exportQuery, page: p })
        all.push(...res.data.items)
        if (all.length >= res.data.total || res.data.items.length === 0) break
        p += 1
      }
      const countsAs = (tx: Transaction) =>
        tx.transaction_type === 'credit'
          ? 'income'
          : tx.excluded_reason === 'card_payment'
          ? 'card repayment'
          : tx.excluded_reason === 'internal_transfer'
          ? 'transfer'
          : 'spending'
      const q = (s: string) => `"${(s || '').replace(/"/g, '""')}"`
      const headers = [
        'Date', 'Description', 'Merchant', 'Account', 'Category', 'Type', 'Amount',
        'Currency', 'Counts as', 'Excluded reason', 'Commitment', 'On finance',
      ]
      const rows = all.map((tx) => [
        new Date(tx.transaction_date).toLocaleDateString('en-GB'),
        q(tx.description),
        q(tx.merchant_name || ''),
        q(accountName(tx.account_id)),
        q(tx.category || 'Uncategorized'),
        tx.transaction_type,
        tx.amount.toFixed(2),
        tx.currency,
        countsAs(tx),
        tx.excluded_reason || '',
        tx.is_commitment ? 'yes' : '',
        tx.is_financed ? 'yes' : '',
      ])
      const blob = new Blob([[headers.join(','), ...rows.map((r) => r.join(','))].join('\n')], {
        type: 'text/csv;charset=utf-8;',
      })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `nilu_ledger_${data.period_start}_to_${data.period_end}.csv`
      link.click()
    } catch (e) {
      console.error('CSV export failed', e)
      showToast('Export failed', { tone: 'err' })
    }
  }

  // The breakdown (donut + merchants) follows the active scope drill; falls
  // back to the full-period `data` while a scope is loading or inactive. The
  // label is only shown once its matching data has landed, so the caption and
  // the numbers beneath it always agree.
  const breakdownData = breakdown ? breakdown.data : data
  const maxCat = breakdownData?.by_category[0]?.total ?? 1
  const scopeLabel = breakdown ? breakdown.label : ''
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const listCategories = Array.from(new Set([...facets.categories])).sort()

  const delta = data && prevTotal != null ? data.total_spent - prevTotal : null
  const deltaEl =
    delta === null ? null : (
      <div className={`text-xs mt-1 ${delta <= 0 ? 'text-pos' : 'text-warn'}`}>
        {delta === 0
          ? 'same as the previous period'
          : `${gbp(Math.abs(delta))} ${delta < 0 ? 'less than' : 'more than'} the previous period`}
      </div>
    )

  return (
    <div ref={revealRef} className="max-w-6xl mx-auto px-4 py-6 sm:py-10">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <h1 className="font-display font-bold text-2xl sm:text-3xl text-slate-50">Spending</h1>
        <div className="flex flex-wrap gap-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={period === p.key ? 'seg-active' : 'seg'}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* The lens: what the headline means. */}
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <div className="flex gap-0.5">
          <button onClick={() => setLens('money_out')} className={lens === 'money_out' ? 'seg-active' : 'seg'}>
            Money out
          </button>
          <button onClick={() => setLens('purchases')} className={lens === 'purchases' ? 'seg-active' : 'seg'}>
            Purchases
          </button>
        </div>
        <span className="text-xs text-slate-500">
          {lens === 'money_out'
            ? 'cash that actually left your bank — reconciles to your statement'
            : 'spend booked when you buy, split by cash vs credit'}
        </span>
      </div>

      {/* Exclusions (commitments / transfers / card payments) all live in one
          place — the Filters panel below. When a drill is active, a prominent
          reset sits right here, next to the figures it's scoping. */}
      {chips.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 mb-5 rounded-xl border border-accent/25 bg-accent/[0.06] px-4 py-3">
          <span className="text-sm text-slate-300">
            You're viewing a filtered slice — {chips.length} filter{chips.length !== 1 ? 's' : ''} applied.
          </span>
          <button onClick={clearAllFilters} className="btn-ghost !py-1.5 shrink-0">
            <X className="w-4 h-4" />
            Remove all filters
          </button>
        </div>
      ) : (
        <div className="mb-5" />
      )}

      <MonthlySpendingChart excludeCommitments={excludeCommitments} />

      {period === 'custom' && (
        <div className="flex flex-wrap gap-3 mb-6">
          <input type="date" value={frm} onChange={(e) => setFrm(e.target.value)} className="input !w-auto" />
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="input !w-auto" />
        </div>
      )}

      {loading || !data ? (
        <div className="text-center py-16 text-slate-500">Loading spending…</div>
      ) : (
        <>
          <p className="text-sm text-slate-500 mb-4">
            {longDate(data.period_start)} – {longDate(data.period_end)}
          </p>

          {lens === 'purchases' ? (
          <>
          {/* Headline split — each tile filters the list below. */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <button
              type="button" data-reveal
              onClick={() => drill({ kind: drillKind === 'spend' ? null : 'spend', category: '', merchant: '' })}
              className={`card-pad text-left w-full hover:bg-white/[0.03] transition-colors group ${drillKind === 'spend' ? '!border-accent/40' : ''}`}
            >
              <div className="text-sm text-slate-400 mb-1 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  Total spent
                  <InfoTip text={EXPLAIN.spentInPeriod} side="bottom" align="left" />
                </span>
                <span className="text-xs text-slate-600 group-hover:text-accent transition-colors">View →</span>
              </div>
              <div className="stat-figure text-3xl text-slate-50">
                <AnimatedNumber value={data.total_spent} />
              </div>
              <div className="text-xs text-slate-500 mt-1">the two figures beside this, combined</div>
              {deltaEl}
            </button>
            <button
              type="button" data-reveal
              onClick={() => drill({ kind: drillKind === 'cash' ? null : 'cash', category: '', merchant: '' })}
              className={`card-pad text-left w-full hover:bg-white/[0.03] transition-colors group ${drillKind === 'cash' ? '!border-accent/40' : ''}`}
            >
              <div className="text-sm text-slate-400 mb-1 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  Paid from bank
                  <InfoTip text={EXPLAIN.paidFromCash} side="bottom" align="left" />
                </span>
                <span className="text-xs text-slate-600 group-hover:text-accent transition-colors">View →</span>
              </div>
              <div className="stat-figure text-3xl text-slate-100">{gbp(data.paid_from_cash)}</div>
              <div className="text-xs text-slate-500 mt-1">left your bank accounts directly</div>
            </button>
            <button
              type="button" data-reveal
              onClick={() => drill({ kind: drillKind === 'credit' ? null : 'credit', category: '', merchant: '' })}
              className={`card-pad text-left w-full hover:bg-white/[0.03] transition-colors group ${drillKind === 'credit' ? '!border-accent/40' : ''}`}
            >
              <div className="text-sm text-slate-400 mb-1 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  Charged to credit
                  <InfoTip text={EXPLAIN.chargedToCredit} side="bottom" align="left" />
                </span>
                <span className="text-xs text-slate-600 group-hover:text-accent transition-colors">View →</span>
              </div>
              <div className="stat-figure text-3xl text-warn">{gbp(data.charged_to_credit)}</div>
              <div className="text-xs text-slate-500 mt-1">deferred — paid later on your cards</div>
            </button>
          </div>

          {/* Make the split legible: the identity, not just three numbers. */}
          <p className="text-xs text-slate-500 mb-6 tnum">
            Total spent {gbp(data.total_spent)} = paid from bank {gbp(data.paid_from_cash)} + charged to credit {gbp(data.charged_to_credit)}
          </p>
          </>
          ) : (
          <>
            {/* Money out of my bank — the default: cash that actually left. */}
            <button
              type="button" data-reveal
              onClick={() => drill({ kind: drillKind === 'money_out' ? null : 'money_out', category: '', merchant: '' })}
              className={`card-pad text-left w-full hover:bg-white/[0.03] transition-colors group mb-4 ${drillKind === 'money_out' ? '!border-accent/40' : ''}`}
            >
              <div className="text-sm text-slate-400 mb-1 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  Money out of my bank
                  <InfoTip text={EXPLAIN.moneyOut} side="bottom" align="left" />
                </span>
                <span className="text-xs text-slate-600 group-hover:text-accent transition-colors">View →</span>
              </div>
              <div className="stat-figure text-4xl text-slate-50">
                <AnimatedNumber value={data.total_spent} />
              </div>
              <div className="text-xs text-slate-500 mt-1">
                cash that actually left your accounts — reconciles to your bank statement
              </div>
              {deltaEl}
            </button>

            {data.composition && (
              <div className="card-pad mb-6" data-reveal>
                <div className="text-xs text-slate-500 mb-3 flex items-center justify-between gap-2">
                  <span>What's inside this figure</span>
                  <button onClick={() => setShowFilters(true)} className="text-accent hover:underline">
                    Exclude any of these →
                  </button>
                </div>
                <div className="space-y-2">
                  {[
                    { label: 'Everyday spending', amount: data.composition.other },
                    { label: 'Commitments (bills)', amount: data.composition.commitments, hidden: excludeCommitments },
                    { label: 'Card repayments', amount: data.composition.card_repayments, hidden: hideCardPayments },
                    { label: 'Transfers between accounts', amount: data.composition.transfers, hidden: hideTransfers },
                  ]
                    .filter((r) => r.amount > 0 || r.hidden)
                    .map((r) => (
                      <div key={r.label} className="flex items-center justify-between text-sm">
                        <span className="text-slate-300">{r.label}</span>
                        {r.hidden ? (
                          <span className="text-xs text-slate-600">excluded</span>
                        ) : (
                          <span className="tnum text-slate-100">{gbp(r.amount)}</span>
                        )}
                      </div>
                    ))}
                </div>
              </div>
            )}
          </>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6 mb-8">
            {/* Categories */}
            <div className="card-pad" data-reveal>
              <h2 className="font-display font-semibold text-slate-100 mb-4">
                By category
                {scopeLabel && <span className="ml-2 text-xs font-normal text-accent">{scopeLabel}</span>}
              </h2>
              <CategoryDonut categories={(breakdownData ?? data).by_category} total={(breakdownData ?? data).total_spent} />
              <div className="space-y-4">
                {(breakdownData ?? data).by_category.map((c, i) => (
                  <button
                    type="button"
                    key={c.category}
                    onClick={() => drill({ category: c.category, merchant: '' })}
                    className="block w-full text-left group"
                  >
                    <div className="flex justify-between gap-3 text-sm mb-1.5">
                      <span className="font-medium text-slate-300 min-w-0 truncate group-hover:text-accent transition-colors">{c.category}</span>
                      <span className="font-semibold text-slate-100 tnum shrink-0">{gbp(c.total)}</span>
                    </div>
                    <div className="bg-white/[0.06] rounded-full h-2 overflow-hidden">
                      <div
                        className="h-2 rounded-full"
                        style={{
                          width: `${(c.total / maxCat) * 100}%`,
                          backgroundColor: BAR_COLORS[i % BAR_COLORS.length],
                        }}
                      />
                    </div>
                    <div className="text-xs text-slate-600 mt-1">
                      {c.count} transaction{c.count !== 1 ? 's' : ''}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Top merchants */}
            <div className="card-pad" data-reveal>
              <h2 className="font-display font-semibold text-slate-100 mb-4">
                {showAllMerchants ? 'All merchants' : 'Top merchants'}
                {scopeLabel && <span className="ml-2 text-xs font-normal text-accent">{scopeLabel}</span>}
              </h2>
              <div className={`space-y-3 ${showAllMerchants ? 'max-h-96 overflow-y-auto pr-1 -mr-1' : ''}`}>
                {(showAllMerchants ? (breakdownData ?? data).top_merchants : (breakdownData ?? data).top_merchants.slice(0, MERCHANTS_DEFAULT)).map((m, i) => (
                  <button
                    type="button"
                    key={m.merchant}
                    onClick={() => drill({ merchant: m.merchant, category: '' })}
                    className="flex items-center gap-3 w-full text-left group"
                  >
                    <div
                      className={`w-7 h-7 shrink-0 flex items-center justify-center rounded-lg text-xs font-bold ${
                        i < 3 ? 'bg-accent/15 text-accent' : 'bg-white/[0.06] text-slate-500'
                      }`}
                    >
                      {i + 1}
                    </div>
                    <div className="flex-1 min-w-0 text-sm font-medium text-slate-200 truncate group-hover:text-accent transition-colors">{m.merchant}</div>
                    <div className="text-sm font-semibold text-slate-100 tnum shrink-0">{gbp(m.total)}</div>
                  </button>
                ))}
              </div>
              {(breakdownData ?? data).top_merchants.length > MERCHANTS_DEFAULT && (
                <button
                  type="button"
                  onClick={() => setShowAllMerchants((v) => !v)}
                  className="mt-4 text-sm text-accent hover:underline"
                >
                  {showAllMerchants
                    ? 'Show less'
                    : `Show all ${(breakdownData ?? data).top_merchants.length} merchants`}
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {/* ---- Activity: the transactions behind the figures ---- */}
      <div ref={listRef} className="scroll-mt-20">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-baseline gap-3">
            <h2 className="font-display font-semibold text-xl text-slate-100">Activity</h2>
            <span className="text-sm text-slate-500">
              {total} transaction{total !== 1 ? 's' : ''}
            </span>
          </div>
          <button
            onClick={downloadCSV}
            className="btn-ghost"
            title="Every transaction in this period — including transfers and card payments — with our derived flags (counts-as, commitment, on-finance). A faithful, auditable copy, not the filtered view."
          >
            <ArrowDownToLine className="w-4 h-4" />
            Export ledger
          </button>
        </div>

        {chips.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 mb-4">
            {chips.map((c) => (
              <button
                key={c.key}
                onClick={c.onClear}
                className="inline-flex items-center gap-1.5 chip hover:bg-accent/15 hover:text-accent transition-colors"
              >
                {c.label}
                <X className="w-3 h-3" />
              </button>
            ))}
            <button onClick={clearAllFilters} className="text-xs text-accent hover:underline">
              Clear all
            </button>
          </div>
        )}

        {/* Search + filter bar */}
        <div className="card p-4 mb-4">
          <div className="flex flex-col md:flex-row gap-3">
            <input
              type="text"
              placeholder="Search description or merchant…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input flex-1"
            />
            <select
              value={selectedAccount}
              onChange={(e) => setSelectedAccount(e.target.value)}
              className="input md:!w-56"
            >
              <option value="">All accounts</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.display_name}
                </option>
              ))}
            </select>
            <button
              onClick={() => setShowFilters((s) => !s)}
              className={`btn ${showFilters || chips.length > 0 ? 'bg-accent/15 text-accent' : 'bg-white/[0.06] text-slate-200 hover:bg-white/[0.1]'}`}
              aria-expanded={showFilters}
            >
              <SlidersHorizontal className="w-4 h-4" />
              Filters
              <ChevronDown className={`w-4 h-4 transition-transform ${showFilters ? 'rotate-180' : ''}`} />
            </button>
          </div>

          {showFilters && (
            <div className="mt-4 pt-4 border-t border-white/[0.06]">
              <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
                <div>
                  <label className="label">Start date</label>
                  <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="input" />
                </div>
                <div>
                  <label className="label">End date</label>
                  <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="input" />
                </div>
                <div>
                  <label className="label">Min amount</label>
                  <input
                    type="number" step="0.01" placeholder="0.00"
                    value={minAmount} onChange={(e) => setMinAmount(e.target.value)} className="input"
                  />
                </div>
                <div>
                  <label className="label">Max amount</label>
                  <input
                    type="number" step="0.01" placeholder="999999.99"
                    value={maxAmount} onChange={(e) => setMaxAmount(e.target.value)} className="input"
                  />
                </div>
              </div>

              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
                <div>
                  <label className="label">Merchant</label>
                  <select value={selectedMerchant} onChange={(e) => setSelectedMerchant(e.target.value)} className="input">
                    <option value="">All merchants</option>
                    {facets.merchants.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Type</label>
                  <select value={selectedType} onChange={(e) => setSelectedType(e.target.value)} className="input">
                    <option value="">All transactions</option>
                    <option value="debit">Expenses only</option>
                    <option value="credit">Income only</option>
                  </select>
                </div>
                <div>
                  <label className="label">Categories</label>
                  <div className="border border-white/10 rounded-xl p-2 max-h-40 overflow-y-auto bg-white/[0.03]">
                    {['Uncategorized', ...listCategories].map((category) => {
                      const isSelected = selectedCategories.includes(category)
                      return (
                        <label key={category} className="flex items-center py-1 px-2 hover:bg-white/[0.04] rounded-lg cursor-pointer">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => {
                              if (e.target.checked) setSelectedCategories([...selectedCategories, category])
                              else setSelectedCategories(selectedCategories.filter((c) => c !== category))
                            }}
                            className="checkbox mr-2"
                          />
                          <span className="text-sm text-slate-300">{category}</span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              </div>

              <div className="mb-4">
                <p className="text-xs text-slate-500 mb-2">
                  Everything is shown by default. These aren't spending, so hide them if you like —
                  they stay in your list, just labelled.
                </p>
                <label className="flex items-start sm:items-center cursor-pointer mb-2">
                  <input
                    type="checkbox"
                    checked={hideTransfers}
                    onChange={(e) => setHideTransfers(e.target.checked)}
                    className="checkbox mt-0.5 sm:mt-0"
                  />
                  <span className="ml-2 text-sm text-slate-300">
                    Hide transfers between my accounts
                    <span className="ml-1 text-xs text-slate-500">(money moving, not leaving you)</span>
                  </span>
                </label>
                <label className="flex items-start sm:items-center cursor-pointer mb-2">
                  <input
                    type="checkbox"
                    checked={hideCardPayments}
                    onChange={(e) => setHideCardPayments(e.target.checked)}
                    className="checkbox mt-0.5 sm:mt-0"
                  />
                  <span className="ml-2 text-sm text-slate-300">
                    Hide card repayments
                    <span className="ml-1 text-xs text-slate-500">(paying off a card, not new spending)</span>
                  </span>
                </label>
                <label className="flex items-start sm:items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={excludeCommitments}
                    onChange={(e) => toggleExcludeCommitments(e.target.checked)}
                    className="checkbox mt-0.5 sm:mt-0"
                  />
                  <span className="ml-2 text-sm text-slate-300">
                    Exclude commitments
                    <span className="ml-1 text-xs text-slate-500">(rent, salary, subscriptions — show only spending you control)</span>
                  </span>
                </label>
              </div>

              <button onClick={clearAllFilters} className="btn-ghost">
                Clear all filters
              </button>
            </div>
          )}
        </div>

        {/* Bulk category bar */}
        {!listLoading && items.length > 0 && (
          <div className="card p-4 mb-4">
            {!bulkMode ? (
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                <div className="text-sm text-slate-400">
                  {selectedIds.size > 0
                    ? `${selectedIds.size} transaction${selectedIds.size !== 1 ? 's' : ''} selected`
                    : 'Select transactions to update their category'}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => setSelectedIds(new Set(items.map((t) => t.id)))}
                    className="btn-ghost !py-1.5"
                  >
                    Select page
                  </button>
                  {selectedIds.size > 0 && (
                    <button onClick={() => setSelectedIds(new Set())} className="btn-ghost !py-1.5">
                      Deselect all
                    </button>
                  )}
                  <button
                    onClick={() => setBulkMode(true)}
                    disabled={selectedIds.size === 0}
                    className="btn-primary !py-1.5"
                  >
                    Set category
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <select
                  value={bulkCategory}
                  onChange={(e) => setBulkCategory(e.target.value)}
                  className="input flex-1"
                >
                  <option value="">Uncategorized</option>
                  {listCategories.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <button onClick={bulkApply} disabled={bulkBusy} className="btn-primary">
                  {bulkBusy ? 'Updating…' : `Apply to ${selectedIds.size}`}
                </button>
                <button onClick={() => setBulkMode(false)} className="btn-ghost">
                  Cancel
                </button>
              </div>
            )}
          </div>
        )}

        {/* The list */}
        <div className="card overflow-hidden">
          {listLoading ? (
            <div className="p-8 text-center text-slate-500">Loading transactions…</div>
          ) : items.length === 0 ? (
            <div className="p-8 text-center text-slate-500">
              No transactions match. Adjust the filters, or widen the period above.
            </div>
          ) : (
            <>
              {/* Mobile cards */}
              <div className="md:hidden divide-y divide-white/[0.06]">
                {items.map((tx) => (
                  <div
                    key={tx.id}
                    className={`p-4 flex items-start gap-3`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(tx.id)}
                      onChange={() => toggleSelected(tx.id)}
                      className="checkbox mt-1"
                    />
                    <button onClick={() => setSheetTx(tx)} className="flex-1 min-w-0 text-left">
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-sm font-medium text-slate-100 break-words">
                          {tx.merchant_name || tx.description}
                        </span>
                        <span className={`text-sm font-semibold whitespace-nowrap tnum ${
                          tx.transaction_type === 'credit' ? 'text-pos' : 'text-slate-200'
                        }`}>
                          {tx.transaction_type === 'credit' ? '+' : '−'}
                          {money(tx.amount, tx.currency)}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        {dateDMY(tx.transaction_date)} · {accountName(tx.account_id)}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {tx.category && <span className="chip">{tx.category}</span>}
                        {tx.is_commitment && <span className="chip-warn">Commitment</span>}
                        {tx.is_financed && <span className="chip-info">On finance</span>}
                        {tx.excluded_reason && (
                          <span className="chip">
                            {tx.excluded_reason === 'internal_transfer' ? 'transfer' : 'card payment'}
                          </span>
                        )}
                      </div>
                    </button>
                  </div>
                ))}
              </div>

              {/* Desktop table */}
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-white/[0.02] border-b border-white/[0.06]">
                    <tr>
                      <th className="px-4 py-3 w-10"></th>
                      <th
                        className="th cursor-pointer hover:bg-white/[0.04] select-none"
                        onClick={() => {
                          setSortDirection(sortField === 'date' && sortDirection === 'desc' ? 'asc' : 'desc')
                          setSortField('date')
                        }}
                      >
                        <div className="flex items-center gap-1">
                          Date
                          {sortField === 'date' && (
                            <span className="text-accent">{sortDirection === 'asc' ? '↑' : '↓'}</span>
                          )}
                        </div>
                      </th>
                      <th className="th">Description</th>
                      <th className="th">Account</th>
                      <th className="th">Category</th>
                      <th
                        className="th !text-right cursor-pointer hover:bg-white/[0.04] select-none"
                        onClick={() => {
                          setSortDirection(sortField === 'amount' && sortDirection === 'desc' ? 'asc' : 'desc')
                          setSortField('amount')
                        }}
                      >
                        <div className="flex items-center justify-end gap-1">
                          Amount
                          {sortField === 'amount' && (
                            <span className="text-accent">{sortDirection === 'asc' ? '↑' : '↓'}</span>
                          )}
                        </div>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.06]">
                    {items.map((tx) => (
                      <tr
                        key={tx.id}
                        onClick={() => setSheetTx(tx)}
                        className={`hover:bg-white/[0.03] transition-colors cursor-pointer`}
                      >
                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={selectedIds.has(tx.id)}
                            onChange={() => toggleSelected(tx.id)}
                            className="checkbox"
                          />
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-400 whitespace-nowrap tnum">
                          {dateDMY(tx.transaction_date)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="text-sm font-medium text-slate-100">
                            {tx.merchant_name || tx.description}
                          </div>
                          {tx.merchant_name && (
                            <div className="text-xs text-slate-500">{tx.description}</div>
                          )}
                          <div className="flex flex-wrap gap-1 mt-1">
                            {tx.is_commitment && <span className="chip-warn">Commitment</span>}
                            {tx.is_financed && <span className="chip-info">On finance</span>}
                            {tx.excluded_reason && (
                              <span className="chip">
                                {tx.excluded_reason === 'internal_transfer' ? 'transfer' : 'card payment'}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-400">{accountName(tx.account_id)}</td>
                        <td className="px-4 py-3">
                          {tx.category ? (
                            <span className="chip">{tx.category}</span>
                          ) : (
                            <span className="text-xs text-slate-600">Uncategorized</span>
                          )}
                        </td>
                        <td className={`px-4 py-3 text-sm font-semibold text-right whitespace-nowrap tnum ${
                          tx.transaction_type === 'credit' ? 'text-pos' : 'text-slate-200'
                        }`}>
                          {tx.transaction_type === 'credit' ? '+' : '−'}
                          {money(tx.amount, tx.currency)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="px-4 py-3 border-t border-white/[0.06] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                  <div className="text-sm text-slate-400">
                    Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="px-3 py-1 rounded-lg text-sm border border-white/10 text-slate-300 hover:bg-white/[0.06] disabled:opacity-40 transition-colors"
                    >
                      Previous
                    </button>
                    <span className="px-3 text-sm text-slate-500">
                      Page {page} of {totalPages}
                    </span>
                    <button
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                      className="px-3 py-1 rounded-lg text-sm border border-white/10 text-slate-300 hover:bg-white/[0.06] disabled:opacity-40 transition-colors"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {sheetTx && (
        <TransactionDetailSheet
          transaction={sheetTx}
          accountName={accountName(sheetTx.account_id)}
          categories={listCategories}
          onClose={() => setSheetTx(null)}
          onChanged={(patch) => {
            if (patch) patchItem(sheetTx.id, patch)
            reloadAll()
          }}
          onCreateRule={() => {
            setRuleTx(sheetTx)
            setSheetTx(null)
          }}
          onPayOnFinance={() => {
            setFinanceTx(sheetTx)
            setSheetTx(null)
          }}
        />
      )}

      {ruleTx && (
        <AddRuleModal
          initialPattern={(ruleTx.merchant_name || ruleTx.description || '').trim()}
          initialCategory={ruleTx.category ?? ''}
          categories={listCategories}
          onClose={() => setRuleTx(null)}
          onAdded={(result) => {
            setRuleTx(null)
            showToast(
              result?.applied
                ? `Rule added · recategorized ${result.changed} transaction${result.changed !== 1 ? 's' : ''}`
                : 'Rule added',
            )
            reloadAll()
          }}
        />
      )}

      {financeTx && (
        <PayOnFinanceModal
          transaction={financeTx}
          onClose={() => setFinanceTx(null)}
          onDone={(label) => {
            setFinanceTx(null)
            showToast(`"${label}" moved to a payment plan`)
            reloadAll()
          }}
        />
      )}
    </div>
  )
}

// Donut of category proportions. Top slices are kept; the long tail is grouped
// into "Other" so the chart reads at a glance — the bars below carry the detail.
function CategoryDonut({ categories, total }: { categories: CategorySlice[]; total: number }) {
  if (!categories.length || total <= 0) return null

  const TOP = 6
  const sorted = [...categories].sort((a, b) => b.total - a.total)
  const head = sorted.slice(0, TOP)
  const tail = sorted.slice(TOP)
  const slices = head.map((c, i) => ({
    name: c.category,
    value: c.total,
    color: BAR_COLORS[i % BAR_COLORS.length],
  }))
  if (tail.length) {
    slices.push({
      name: `Other (${tail.length})`,
      value: tail.reduce((s, c) => s + c.total, 0),
      color: '#475569',
    })
  }

  return (
    <div className="flex flex-col sm:flex-row items-center gap-4 mb-6">
      <div className="relative w-44 h-44 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={slices}
              dataKey="value"
              nameKey="name"
              innerRadius="62%"
              outerRadius="100%"
              paddingAngle={2}
              stroke="none"
            >
              {slices.map((s) => (
                <Cell key={s.name} fill={s.color} />
              ))}
            </Pie>
            <Tooltip
              formatter={(v, n) => {
                const num = Number(v)
                return [`${gbp(num)} · ${Math.round((num / total) * 100)}%`, n as string]
              }}
              contentStyle={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 12, fontSize: 13 }}
              itemStyle={{ color: '#e2e8f0' }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-[11px] text-slate-500">Total</span>
          <span className="font-display font-semibold text-slate-100 tnum text-sm">{gbp(total)}</span>
        </div>
      </div>
      <ul className="flex-1 min-w-0 grid grid-cols-1 gap-1.5 w-full">
        {slices.map((s) => (
          <li key={s.name} className="flex items-center gap-2 text-sm">
            <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: s.color }} />
            <span className="min-w-0 truncate text-slate-300">{s.name}</span>
            <span className="ml-auto shrink-0 text-slate-500 tnum text-xs">
              {Math.round((s.value / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
