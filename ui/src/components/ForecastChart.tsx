import { useEffect, useReducer, useRef, useState } from 'react'
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
import { gbp0 as gbp, dateDayMonth as shortDate } from '../lib/format'
import InfoTip from './ui/InfoTip'
import ForecastSummary, { OVERDRAFT_LINE_LABEL, type AccountBreach } from './ForecastSummary'
import { EXPLAIN } from '../copy/statExplainers'
import ForecastError from './forecast/ForecastError'
import LateIncomeNote from './forecast/LateIncomeNote'
import { FORECAST_TIMEOUT_MS, focusAfter, forecastReducer, withTimeout, type ForecastView } from '../lib/forecastLoad'

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
  account_breaches: AccountBreach[]
  unassigned_attributed_to: string | null
  timeline: ForecastPoint[]
  // Expected income that hasn't arrived: shown, never in the line (T-08-7, T-08-10).
  late_income?: { amount: number | string }[]
  late_planned?: { amount: number | string }[]
}

const HORIZONS: { key: string; label: string }[] = [
  { key: 'payday', label: 'Payday' },
  { key: '30', label: '30d' },
  { key: '90', label: '90d' },
  { key: '180', label: '6mo' },
  { key: '365', label: '1yr' },
]

function ForecastTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const point: ForecastPoint = payload[0].payload
  return (
    <div className="bg-card2 border border-white/10 rounded-xl shadow-pop p-3 text-sm">
      <div className="font-medium text-slate-200">{shortDate(point.date)}</div>
      <div className="text-slate-100 tnum">Balance: {gbp(point.balance)}</div>
      {point.events?.map((e, i) => (
        <div key={i} className={e.amount >= 0 ? 'text-pos' : 'text-neg'}>
          {e.amount >= 0 ? '+' : ''}{gbp(e.amount)} · {e.label}
        </div>
      ))}
    </div>
  )
}

export default function ForecastChart({ refreshKey }: { refreshKey?: number }) {
  const [horizon, setHorizon] = useState('30')
  const [attempt, setAttempt] = useState(0)
  const [view, dispatch] = useReducer(
    forecastReducer<Forecast>,
    { status: 'loading' } as ForecastView<Forecast>,
  )
  const headingRef = useRef<HTMLHeadingElement>(null)
  const retryRef = useRef<HTMLButtonElement>(null)
  const prevView = useRef(view)

  useEffect(() => {
    let cancelled = false
    dispatch({ type: 'start' })
    // A request that never answers ends in the error state too (F2).
    withTimeout(analyticsAPI.getForecast(horizon), FORECAST_TIMEOUT_MS)
      .then((res) => {
        if (cancelled) return
        // Decimal fields arrive as strings — coerce for the chart.
        const f = res.data as Forecast
        f.timeline = f.timeline.map((p) => ({ ...p, balance: Number(p.balance) }))
        f.min_balance = Number(f.min_balance)
        f.overdraft_limit = Number(f.overdraft_limit)
        dispatch({ type: 'loaded', data: f })
      })
      .catch(() => {
        // Only the spec's sentence is shown. The error object isn't logged
        // either: it can carry the request URL and the server's detail.
        if (cancelled) return
        console.warn('Forecast failed to load')
        dispatch({ type: 'failed' })
      })
    return () => {
      cancelled = true
    }
  }, [horizon, refreshKey, attempt])

  useEffect(() => {
    const target = focusAfter(prevView.current, view)
    if (target === 'heading') headingRef.current?.focus()
    if (target === 'retry') retryRef.current?.focus()
    prevView.current = view
  }, [view])

  const retry = () => {
    dispatch({ type: 'retry' })
    setAttempt((a) => a + 1)
  }

  const data = view.status === 'ready' ? view.data : null
  const hasOverdraft = (data?.overdraft_limit ?? 0) > 0

  return (
    <div className="card-pad h-full">
      <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="font-display font-semibold text-slate-100 flex items-center gap-1.5 rounded focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent/60"
        >
          Where it's going
          <InfoTip text={EXPLAIN.forecast} side="bottom" align="left" />
        </h2>
        <div className="flex gap-0.5">
          {HORIZONS.map((h) => (
            <button
              key={h.key}
              onClick={() => setHorizon(h.key)}
              className={horizon === h.key ? 'seg-active' : 'seg'}
            >
              {h.label}
            </button>
          ))}
        </div>
      </div>

      {view.status === 'error' ? (
        <ForecastError ref={retryRef} retrying={view.retrying} onRetry={retry} />
      ) : !data ? (
        <div className="h-64 flex items-center justify-center text-slate-400">Loading forecast…</div>
      ) : (
        <>
          <ForecastSummary data={data} />
          <LateIncomeNote items={[...(data.late_income ?? []), ...(data.late_planned ?? [])]} />
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={data.timeline} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="balfill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2DD4A7" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#2DD4A7" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={28} fontSize={12} tickLine={false} axisLine={false} />
              <YAxis tickFormatter={(v) => gbp(v)} width={70} fontSize={12} tickLine={false} axisLine={false} />
              <Tooltip content={<ForecastTooltip />} />
              <ReferenceLine y={0} stroke="#475569" strokeWidth={1} />
              {hasOverdraft && (
                <ReferenceLine
                  y={-data.overdraft_limit}
                  stroke="#FB7185"
                  strokeDasharray="4 4"
                  label={{ value: OVERDRAFT_LINE_LABEL, position: 'insideBottomRight', fontSize: 11, fill: '#FB7185' }}
                />
              )}
              <Area type="monotone" dataKey="balance" stroke="#2DD4A7" strokeWidth={2} fill="url(#balfill)" />
            </AreaChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  )
}
