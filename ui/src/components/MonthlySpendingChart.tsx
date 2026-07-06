import { useEffect, useState } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { analyticsAPI } from '../services/api'
import { gbp0 as gbp, monthLabel } from '../lib/format'

interface MonthSpend {
  month: string // YYYY-MM
  total: number
  charged_to_credit: number
  paid_from_cash: number
}

function TrendTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const m: MonthSpend = payload[0].payload
  return (
    <div className="bg-card2 border border-white/10 rounded-xl shadow-pop p-3 text-sm">
      <div className="font-medium text-slate-200">{monthLabel(m.month)}</div>
      <div className="text-slate-100 tnum">Total: {gbp(m.total)}</div>
      <div className="text-slate-400 tnum">From cash: {gbp(m.paid_from_cash)}</div>
      <div className="text-warn tnum">On credit: {gbp(m.charged_to_credit)}</div>
    </div>
  )
}

export default function MonthlySpendingChart({
  excludeCommitments = false,
}: {
  excludeCommitments?: boolean
}) {
  const [months, setMonths] = useState(6)
  const [data, setData] = useState<MonthSpend[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    analyticsAPI
      .getSpendingTrend(months, excludeCommitments)
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
  }, [months, excludeCommitments])

  const max = Math.max(0, ...data.map((d) => d.total))
  const worst = data.find((d) => d.total === max && max > 0)
  const chartData = data.map((d) => ({ ...d, label: monthLabel(d.month) }))

  return (
    <div className="card-pad mb-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="font-display font-semibold text-slate-100">Spending by month</h2>
        <div className="flex gap-0.5">
          {[6, 12].map((n) => (
            <button
              key={n}
              onClick={() => setMonths(n)}
              className={months === n ? 'seg-active' : 'seg'}
            >
              {n} mo
            </button>
          ))}
        </div>
      </div>
      {worst && (
        <p className="text-sm text-slate-500 mb-3">
          Highest: <span className="font-semibold text-neg">{monthLabel(worst.month)}</span> at{' '}
          <span className="tnum">{gbp(worst.total)}</span>
        </p>
      )}
      {loading ? (
        <div className="h-56 flex items-center justify-center text-slate-600">Loading…</div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
            <XAxis dataKey="label" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis tickFormatter={(v) => gbp(v)} width={64} fontSize={12} tickLine={false} axisLine={false} />
            <Tooltip content={<TrendTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
            <Bar dataKey="total" radius={[6, 6, 0, 0]}>
              {chartData.map((d) => (
                <Cell key={d.month} fill={d.total === max && max > 0 ? '#FB7185' : '#2DD4A7'} fillOpacity={d.total === max && max > 0 ? 0.9 : 0.75} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
