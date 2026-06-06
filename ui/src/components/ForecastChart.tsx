import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { analyticsAPI } from '../services/api'

interface ForecastEvent {
  label: string
  amount: number
  kind: string
}
interface ForecastPoint {
  date: string
  balance: number
  events: ForecastEvent[]
}
interface Forecast {
  horizon: string
  horizon_end: string
  start_balance: number
  end_balance: number
  min_balance: number
  min_date: string
  overdraft_limit: number
  breaches: string[]
  timeline: ForecastPoint[]
}

const HORIZONS: { key: string; label: string }[] = [
  { key: 'payday', label: 'Payday' },
  { key: '30', label: '30d' },
  { key: '90', label: '90d' },
  { key: '180', label: '6mo' },
  { key: '365', label: '1yr' },
]

const gbp = (n: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 }).format(n)
const shortDate = (d: string) => new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

function ForecastTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const point: ForecastPoint = payload[0].payload
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-3 text-sm">
      <div className="font-medium">{shortDate(point.date)}</div>
      <div className="text-gray-900">Balance: {gbp(point.balance)}</div>
      {point.events?.map((e, i) => (
        <div key={i} className={e.amount >= 0 ? 'text-green-600' : 'text-red-600'}>
          {e.amount >= 0 ? '+' : ''}{gbp(e.amount)} · {e.label}
        </div>
      ))}
    </div>
  )
}

export default function ForecastChart({ refreshKey }: { refreshKey?: number }) {
  const [horizon, setHorizon] = useState('30')
  const [data, setData] = useState<Forecast | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    analyticsAPI
      .getForecast(horizon)
      .then((res) => {
        if (cancelled) return
        // Decimal fields arrive as strings — coerce for the chart.
        const f = res.data as Forecast
        f.timeline = f.timeline.map((p) => ({ ...p, balance: Number(p.balance) }))
        f.min_balance = Number(f.min_balance)
        f.overdraft_limit = Number(f.overdraft_limit)
        setData(f)
      })
      .catch((e) => console.error('Failed to load forecast', e))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [horizon, refreshKey])

  const hasOverdraft = (data?.overdraft_limit ?? 0) > 0
  const breached = (data?.breaches?.length ?? 0) > 0

  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border border-gray-200">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Balance forecast</h2>
        <div className="flex gap-1">
          {HORIZONS.map((h) => (
            <button
              key={h.key}
              onClick={() => setHorizon(h.key)}
              className={`px-2.5 py-1 text-sm rounded-lg ${
                horizon === h.key ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {h.label}
            </button>
          ))}
        </div>
      </div>

      {loading || !data ? (
        <div className="h-64 flex items-center justify-center text-gray-400">Loading forecast…</div>
      ) : (
        <>
          <div className={`mb-3 text-sm ${breached ? 'text-red-600' : 'text-gray-600'}`}>
            {breached && '⚠ '}Lowest point: <span className="font-semibold">{gbp(data.min_balance)}</span> on{' '}
            {shortDate(data.min_date)}
            {data.breaches.includes('overdraft')
              ? ' — exceeds your overdraft limit'
              : data.breaches.includes('zero')
              ? ' — dips into overdraft'
              : ''}
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={data.timeline} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="balfill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2563eb" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#2563eb" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={28} fontSize={12} />
              <YAxis tickFormatter={(v) => gbp(v)} width={70} fontSize={12} />
              <Tooltip content={<ForecastTooltip />} />
              <ReferenceLine y={0} stroke="#9ca3af" strokeWidth={1} />
              {hasOverdraft && (
                <ReferenceLine
                  y={-data.overdraft_limit}
                  stroke="#dc2626"
                  strokeDasharray="4 4"
                  label={{ value: 'overdraft limit', position: 'insideBottomRight', fontSize: 11, fill: '#dc2626' }}
                />
              )}
              <Area type="monotone" dataKey="balance" stroke="#2563eb" strokeWidth={2} fill="url(#balfill)" />
            </AreaChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  )
}
