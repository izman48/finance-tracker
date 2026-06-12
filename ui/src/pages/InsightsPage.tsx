import { useEffect, useState } from 'react'
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

          {/* Headline split */}
          <div className="grid sm:grid-cols-3 gap-4 mb-6">
            <div className="card-pad" data-reveal>
              <div className="text-sm text-slate-400 mb-1">Total spent</div>
              <div className="stat-figure text-3xl text-slate-50">
                <AnimatedNumber value={data.total_spent} />
              </div>
            </div>
            <div className="card-pad" data-reveal>
              <div className="text-sm text-slate-400 mb-1">Paid from cash</div>
              <div className="stat-figure text-3xl text-slate-100">{gbp(data.paid_from_cash)}</div>
            </div>
            <div className="card-pad" data-reveal>
              <div className="text-sm text-slate-400 mb-1">Charged to credit</div>
              <div className="stat-figure text-3xl text-warn">{gbp(data.charged_to_credit)}</div>
              <div className="text-xs text-slate-500 mt-1">deferred — paid later on your cards</div>
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4 sm:gap-6">
            {/* Categories */}
            <div className="card-pad" data-reveal>
              <h2 className="font-display font-semibold text-slate-100 mb-4">By category</h2>
              <div className="space-y-4">
                {data.by_category.map((c, i) => (
                  <div key={c.category}>
                    <div className="flex justify-between text-sm mb-1.5">
                      <span className="font-medium text-slate-300">{c.category}</span>
                      <span className="font-semibold text-slate-100 tnum">{gbp(c.total)}</span>
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
                  </div>
                ))}
              </div>
            </div>

            {/* Top merchants */}
            <div className="card-pad" data-reveal>
              <h2 className="font-display font-semibold text-slate-100 mb-4">Top merchants</h2>
              <div className="space-y-3">
                {data.top_merchants.map((m, i) => (
                  <div key={m.merchant} className="flex items-center gap-3">
                    <div
                      className={`w-7 h-7 flex items-center justify-center rounded-lg text-xs font-bold ${
                        i < 3 ? 'bg-accent/15 text-accent' : 'bg-white/[0.06] text-slate-500'
                      }`}
                    >
                      {i + 1}
                    </div>
                    <div className="flex-1 text-sm font-medium text-slate-200 truncate">{m.merchant}</div>
                    <div className="text-sm font-semibold text-slate-100 tnum">{gbp(m.total)}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
