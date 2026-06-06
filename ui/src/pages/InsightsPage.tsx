import { useEffect, useState } from 'react'
import { analyticsAPI } from '../services/api'
import MonthlySpendingChart from '../components/MonthlySpendingChart'

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

export default function InsightsPage() {
  const [period, setPeriod] = useState('since_payday')
  const [frm, setFrm] = useState('')
  const [to, setTo] = useState('')
  const [data, setData] = useState<Spending | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (period === 'custom' && (!frm || !to)) return
    setLoading(true)
    analyticsAPI
      .getSpending(period, period === 'custom' ? frm : undefined, period === 'custom' ? to : undefined)
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
  }, [period, frm, to])

  const maxCat = data?.by_category[0]?.total ?? 1

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="text-3xl font-bold">Where it went</h1>
        <div className="flex flex-wrap gap-1">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`px-3 py-1.5 text-sm rounded-lg ${
                period === p.key ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <MonthlySpendingChart />

      {period === 'custom' && (
        <div className="flex gap-3 mb-6">
          <input type="date" value={frm} onChange={(e) => setFrm(e.target.value)} className="px-3 py-2 border border-gray-300 rounded-lg" />
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="px-3 py-2 border border-gray-300 rounded-lg" />
        </div>
      )}

      {loading || !data ? (
        <div className="text-center py-16 text-gray-500">Loading spending…</div>
      ) : data.total_spent === 0 ? (
        <div className="text-center py-16 text-gray-500">
          No spending in this period ({longDate(data.period_start)} – {longDate(data.period_end)}).
        </div>
      ) : (
        <>
          <p className="text-sm text-gray-500 mb-4">
            {longDate(data.period_start)} – {longDate(data.period_end)}
          </p>

          {/* Headline split */}
          <div className="grid sm:grid-cols-3 gap-4 mb-8">
            <div className="p-6 bg-white rounded-xl shadow-sm border border-gray-200">
              <div className="text-sm text-gray-500 mb-1">Total spent</div>
              <div className="text-3xl font-bold">{gbp(data.total_spent)}</div>
            </div>
            <div className="p-6 bg-white rounded-xl shadow-sm border border-gray-200">
              <div className="text-sm text-gray-500 mb-1">Paid from cash</div>
              <div className="text-3xl font-bold text-gray-900">{gbp(data.paid_from_cash)}</div>
            </div>
            <div className="p-6 bg-white rounded-xl shadow-sm border border-gray-200">
              <div className="text-sm text-gray-500 mb-1">Charged to credit</div>
              <div className="text-3xl font-bold text-amber-600">{gbp(data.charged_to_credit)}</div>
              <div className="text-xs text-gray-400 mt-1">deferred — paid later on your cards</div>
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            {/* Categories */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h2 className="text-lg font-semibold mb-4">By category</h2>
              <div className="space-y-3">
                {data.by_category.map((c) => (
                  <div key={c.category}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-medium text-gray-700">{c.category}</span>
                      <span className="font-semibold">{gbp(c.total)}</span>
                    </div>
                    <div className="bg-gray-100 rounded-full h-2">
                      <div className="bg-blue-600 h-2 rounded-full" style={{ width: `${(c.total / maxCat) * 100}%` }} />
                    </div>
                    <div className="text-xs text-gray-400 mt-0.5">{c.count} transaction{c.count !== 1 ? 's' : ''}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Top merchants */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h2 className="text-lg font-semibold mb-4">Top merchants</h2>
              <div className="space-y-3">
                {data.top_merchants.map((m, i) => (
                  <div key={m.merchant} className="flex items-center gap-3">
                    <div className="w-6 h-6 flex items-center justify-center bg-gray-100 rounded-full text-xs font-bold text-gray-600">
                      {i + 1}
                    </div>
                    <div className="flex-1 text-sm font-medium text-gray-900">{m.merchant}</div>
                    <div className="text-sm font-semibold">{gbp(m.total)}</div>
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
