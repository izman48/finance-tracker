import { useEffect, useState } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { analyticsAPI } from '../services/api'

interface MonthSpend {
  month: string // YYYY-MM
  total: number
  charged_to_credit: number
  paid_from_cash: number
}

const gbp = (n: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 }).format(n)

function monthLabel(ym: string) {
  const [y, m] = ym.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString('en-GB', { month: 'short', year: '2-digit' })
}

function TrendTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const m: MonthSpend = payload[0].payload
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-3 text-sm">
      <div className="font-medium">{monthLabel(m.month)}</div>
      <div>Total: {gbp(m.total)}</div>
      <div className="text-gray-500">From cash: {gbp(m.paid_from_cash)}</div>
      <div className="text-amber-600">On credit: {gbp(m.charged_to_credit)}</div>
    </div>
  )
}

export default function MonthlySpendingChart() {
  const [months, setMonths] = useState(6)
  const [data, setData] = useState<MonthSpend[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    analyticsAPI
      .getSpendingTrend(months)
      .then((res) => {
        setData(
          res.data.months.map((m: any) => ({
            month: m.month,
            total: Number(m.total),
            charged_to_credit: Number(m.charged_to_credit),
            paid_from_cash: Number(m.paid_from_cash),
          })),
        )
      })
      .catch((e) => console.error('Failed to load spending trend', e))
      .finally(() => setLoading(false))
  }, [months])

  const max = Math.max(0, ...data.map((d) => d.total))
  const worst = data.find((d) => d.total === max && max > 0)
  const chartData = data.map((d) => ({ ...d, label: monthLabel(d.month) }))

  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border border-gray-200 mb-8">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-semibold">Spending by month</h2>
        <div className="flex gap-1">
          {[6, 12].map((n) => (
            <button
              key={n}
              onClick={() => setMonths(n)}
              className={`px-2.5 py-1 text-sm rounded-lg ${months === n ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
            >
              {n} mo
            </button>
          ))}
        </div>
      </div>
      {worst && (
        <p className="text-sm text-gray-500 mb-3">
          Highest: <span className="font-semibold text-red-600">{monthLabel(worst.month)}</span> at {gbp(worst.total)}
        </p>
      )}
      {loading ? (
        <div className="h-56 flex items-center justify-center text-gray-400">Loading…</div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
            <XAxis dataKey="label" fontSize={12} />
            <YAxis tickFormatter={(v) => gbp(v)} width={64} fontSize={12} />
            <Tooltip content={<TrendTooltip />} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
            <Bar dataKey="total" radius={[4, 4, 0, 0]}>
              {chartData.map((d) => (
                <Cell key={d.month} fill={d.total === max && max > 0 ? '#dc2626' : '#2563eb'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
