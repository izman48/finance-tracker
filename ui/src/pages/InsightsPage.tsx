import { useEffect, useState } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { analyticsAPI } from '../services/api'
import MonthlySpendingChart from '../components/MonthlySpendingChart'
import AnimatedNumber from '../components/ui/AnimatedNumber'
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
interface Spending {
  period: string
  period_start: string
  period_end: string
  total_spent: number
  charged_to_credit: number
  paid_from_cash: number
  by_category: CategorySlice[]
  top_merchants: MerchantSlice[]
}

interface DrillFilter {
  category?: string
  merchant?: string
  kind?: string // 'cash' | 'credit'
}
interface DrillTxn {
  id: string
  date: string
  description: string
  merchant: string | null
  amount: number
  category: string
  account: string
  kind: string
}

const MERCHANTS_DEFAULT = 10

const PERIODS = [
  { key: 'since_payday', label: 'Since payday' },
  { key: 'this_month', label: 'This month' },
  { key: 'last_30', label: 'Last 30 days' },
  { key: 'custom', label: 'Custom' },
]

const gbp = (n: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(n)
const longDate = (d: string) => new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

const BAR_COLORS = ['#2DD4A7', '#38BDF8', '#A78BFA', '#FBBF24', '#FB7185', '#34D399', '#818CF8', '#F472B6']

const EXCLUDE_COMMITMENTS_KEY = 'insights.excludeCommitments'

export default function InsightsPage() {
  const [period, setPeriod] = useState('since_payday')
  const [frm, setFrm] = useState('')
  const [to, setTo] = useState('')
  const [data, setData] = useState<Spending | null>(null)
  const [loading, setLoading] = useState(true)
  // Persisted: "how am I spending the rest of my money" is a standing question.
  const [excludeCommitments, setExcludeCommitments] = useState(
    () => localStorage.getItem(EXCLUDE_COMMITMENTS_KEY) === '1',
  )

  const [drill, setDrill] = useState<{ title: string; filter: DrillFilter } | null>(null)
  const [showAllMerchants, setShowAllMerchants] = useState(false)

  const revealRef = useReveal(!loading && !!data)

  const toggleExcludeCommitments = (on: boolean) => {
    setExcludeCommitments(on)
    localStorage.setItem(EXCLUDE_COMMITMENTS_KEY, on ? '1' : '0')
  }

  useEffect(() => {
    if (period === 'custom' && (!frm || !to)) return
    setLoading(true)
    analyticsAPI
      .getSpending(
        period,
        period === 'custom' ? frm : undefined,
        period === 'custom' ? to : undefined,
        excludeCommitments,
      )
      .then((res) => {
        const d = res.data as Spending
        d.total_spent = Number(d.total_spent)
        d.charged_to_credit = Number(d.charged_to_credit)
        d.paid_from_cash = Number(d.paid_from_cash)
        d.by_category = d.by_category.map((c) => ({ ...c, total: Number(c.total) }))
        d.top_merchants = d.top_merchants.map((m) => ({ ...m, total: Number(m.total) }))
        setData(d)
      })
      .catch((e) => console.error('Failed to load spending', e))
      .finally(() => setLoading(false))
  }, [period, frm, to, excludeCommitments])

  const maxCat = data?.by_category[0]?.total ?? 1

  return (
    <div ref={revealRef} className="max-w-6xl mx-auto px-4 py-6 sm:py-10">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <h1 className="font-display font-bold text-2xl sm:text-3xl text-slate-50">Where it went</h1>
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

      {/* Bills are predictable — hide them to see the spending you can change. */}
      <label className="inline-flex items-center gap-2 mb-5 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={excludeCommitments}
          onChange={(e) => toggleExcludeCommitments(e.target.checked)}
          className="checkbox"
        />
        <span className="text-sm text-slate-300">Exclude commitments</span>
        <span className="text-xs text-slate-500">
          (rent, salary, subscriptions — show only the spending I control)
        </span>
      </label>

      <MonthlySpendingChart excludeCommitments={excludeCommitments} />

      {period === 'custom' && (
        <div className="flex flex-wrap gap-3 mb-6">
          <input type="date" value={frm} onChange={(e) => setFrm(e.target.value)} className="input !w-auto" />
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="input !w-auto" />
        </div>
      )}

      {loading || !data ? (
        <div className="text-center py-16 text-slate-500">Loading spending…</div>
      ) : data.total_spent === 0 ? (
        <div className="text-center py-16 text-slate-500">
          No spending in this period ({longDate(data.period_start)} – {longDate(data.period_end)}).
        </div>
      ) : (
        <>
          <p className="text-sm text-slate-500 mb-4">
            {longDate(data.period_start)} – {longDate(data.period_end)}
          </p>

          {/* Headline split — each tile drills into its transactions. */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <button
              type="button" data-reveal
              onClick={() => setDrill({ title: 'All spending', filter: {} })}
              className="card-pad text-left w-full hover:bg-white/[0.03] transition-colors group"
            >
              <div className="text-sm text-slate-400 mb-1 flex items-center justify-between">
                Total spent <span className="text-xs text-slate-600 group-hover:text-accent transition-colors">View →</span>
              </div>
              <div className="stat-figure text-3xl text-slate-50">
                <AnimatedNumber value={data.total_spent} />
              </div>
            </button>
            <button
              type="button" data-reveal
              onClick={() => setDrill({ title: 'Paid from cash', filter: { kind: 'cash' } })}
              className="card-pad text-left w-full hover:bg-white/[0.03] transition-colors group"
            >
              <div className="text-sm text-slate-400 mb-1 flex items-center justify-between">
                Paid from cash <span className="text-xs text-slate-600 group-hover:text-accent transition-colors">View →</span>
              </div>
              <div className="stat-figure text-3xl text-slate-100">{gbp(data.paid_from_cash)}</div>
            </button>
            <button
              type="button" data-reveal
              onClick={() => setDrill({ title: 'Charged to credit', filter: { kind: 'credit' } })}
              className="card-pad text-left w-full hover:bg-white/[0.03] transition-colors group"
            >
              <div className="text-sm text-slate-400 mb-1 flex items-center justify-between">
                Charged to credit <span className="text-xs text-slate-600 group-hover:text-accent transition-colors">View →</span>
              </div>
              <div className="stat-figure text-3xl text-warn">{gbp(data.charged_to_credit)}</div>
              <div className="text-xs text-slate-500 mt-1">deferred — paid later on your cards</div>
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6">
            {/* Categories */}
            <div className="card-pad" data-reveal>
              <h2 className="font-display font-semibold text-slate-100 mb-4">By category</h2>
              <CategoryDonut categories={data.by_category} total={data.total_spent} />
              <div className="space-y-4">
                {data.by_category.map((c, i) => (
                  <button
                    type="button"
                    key={c.category}
                    onClick={() => setDrill({ title: c.category, filter: { category: c.category } })}
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
              </h2>
              <div className="space-y-3">
                {(showAllMerchants ? data.top_merchants : data.top_merchants.slice(0, MERCHANTS_DEFAULT)).map((m, i) => (
                  <button
                    type="button"
                    key={m.merchant}
                    onClick={() => setDrill({ title: m.merchant, filter: { merchant: m.merchant } })}
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
              {data.top_merchants.length > MERCHANTS_DEFAULT && (
                <button
                  type="button"
                  onClick={() => setShowAllMerchants((v) => !v)}
                  className="mt-4 text-sm text-accent hover:underline"
                >
                  {showAllMerchants
                    ? 'Show less'
                    : `Show all ${data.top_merchants.length} merchants`}
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {drill && (
        <DrillModal
          title={drill.title}
          filter={drill.filter}
          context={{ period, frm, to, excludeCommitments }}
          onClose={() => setDrill(null)}
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

// Lists the individual transactions behind a clicked figure (category / merchant
// / cash / credit). Fetches with the same period + exclude-commitments context so
// the list always reconciles with the number that was clicked.
function DrillModal({
  title,
  filter,
  context,
  onClose,
}: {
  title: string
  filter: DrillFilter
  context: { period: string; frm: string; to: string; excludeCommitments: boolean }
  onClose: () => void
}) {
  const [txns, setTxns] = useState<DrillTxn[] | null>(null)

  useEffect(() => {
    analyticsAPI
      .getSpendingTransactions({
        period: context.period,
        frm: context.period === 'custom' ? context.frm : undefined,
        to: context.period === 'custom' ? context.to : undefined,
        excludeCommitments: context.excludeCommitments,
        ...filter,
      })
      .then((res) => setTxns(res.data.map((t: DrillTxn) => ({ ...t, amount: Number(t.amount) }))))
      .catch((e) => {
        console.error('Failed to load drill-down', e)
        setTxns([])
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const total = (txns ?? []).reduce((s, t) => s + t.amount, 0)

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel !max-w-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-50 min-w-0 truncate">{title}</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-200 shrink-0" aria-label="Close">✕</button>
        </div>
        {txns === null ? (
          <div className="py-10 text-center text-slate-500">Loading…</div>
        ) : txns.length === 0 ? (
          <div className="py-10 text-center text-slate-500">No transactions.</div>
        ) : (
          <>
            <p className="text-sm text-slate-400 mb-3">
              {txns.length} transaction{txns.length !== 1 ? 's' : ''} · {gbp(total)}
            </p>
            <ul className="space-y-1 max-h-[60vh] overflow-y-auto -mr-2 pr-2">
              {txns.map((t) => (
                <li key={t.id} className="flex items-center gap-3 py-2 border-b border-white/[0.05] last:border-0">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-slate-200 truncate">{t.merchant || t.description}</div>
                    <div className="text-xs text-slate-500 truncate">
                      {longDate(t.date)} · {t.category}
                      {t.kind === 'credit' && <span className="ml-1 text-warn">· credit</span>}
                      <span className="text-slate-600"> · {t.account}</span>
                    </div>
                  </div>
                  <div className="text-sm font-semibold text-slate-100 tnum shrink-0">{gbp(t.amount)}</div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}
