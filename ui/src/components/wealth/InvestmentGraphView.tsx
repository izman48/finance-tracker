import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { gbp, gbp0 } from '../../lib/format'
import {
  answerSentence, axisLabel, chartPoints, graphStateNotes, inputsLine, LOOK_AHEAD, tablePoints, type ChartPoint, type InvestmentGraph,
} from '../../lib/investments'

export interface InvestmentGraphViewProps {
  status: 'loading' | 'ready' | 'error' | 'not_found'
  graph: InvestmentGraph | null
  months: number
  holdingId: string | null
  /** Every investment, from an unfiltered load: the selector's options. */
  options: { id: string; name: string }[]
  onMonths: (months: number) => void
  onHolding: (id: string | null) => void
  onRetry: () => void
  onAdd: () => void
  onEditGrowth: (id: string) => void
}

const WORTH = '#38BDF8'
const PAID_IN = '#CBD5E1'

/** Wealth > Investments graph (ux T-11-2): one sentence with the answer, the
 *  inputs, then Worth (solid history dots, dashed forecast) and a thin Paid
 *  in line. Every figure is the API's; the chart is not the only source. */
export default function InvestmentGraphView(p: InvestmentGraphViewProps) {
  return (
    <div className="card card-pad">
      <h1 className="font-display font-bold text-2xl text-slate-50 mb-4">Investments</h1>
      <Body {...p} />
    </div>
  )
}

function Body(p: InvestmentGraphViewProps) {
  if (p.status === 'error') {
    return (
      <div role="alert" className="banner-err flex flex-col sm:flex-row sm:items-center gap-3">
        <p className="flex-1">We could not load this graph. Your values are safe. Try again.</p>
        <button type="button" className="btn-ghost" onClick={p.onRetry}>Try again</button>
      </div>
    )
  }
  if (p.status === 'not_found' || (p.status === 'ready' && !p.graph?.holdings?.length)) {
    return (
      <div className="text-center py-8">
        <p className="text-slate-300 mb-4">Add an investment to see its graph.</p>
        <button type="button" className="btn-primary" onClick={p.onAdd}>Add an investment</button>
      </div>
    )
  }
  const graph = p.status === 'ready' ? p.graph : null
  const sentence = graph ? answerSentence(graph.total.answer) : ''
  const inputs = graph ? inputsLine(graph, p.holdingId) : ''
  const notes = graph ? graphStateNotes(graph, p.holdingId) : { historyStarts: false, flat: false }
  const series = graph && (p.holdingId ? graph.holdings.find((h) => h.id === p.holdingId) : graph.total)
  return (
    <>
      <Choices {...p} />
      <p aria-live="polite" className="text-lg text-slate-100 mt-4">{graph ? sentence : 'Working it out…'}</p>
      <p className="text-sm text-slate-400">{inputs}</p>
      {notes.flat && p.holdingId && (
        <p className="text-sm text-slate-400 mt-1">
          Growth is 0% a year, so the forecast is flat.{' '}
          <button type="button" className="text-accent underline" onClick={() => p.onEditGrowth(p.holdingId!)}>
            Set a growth rate
          </button>
        </p>
      )}
      {notes.historyStarts && (
        <p className="text-sm text-slate-400 mt-1">
          Your history starts with your first value. Update the value now and then to see how it moved.
        </p>
      )}
      <div role="img" aria-label={graph ? `${sentence}. ${inputs}` : 'Working it out…'} className="mt-4 h-[280px]">
        {series && <Chart points={chartPoints(series)} today={graph!.as_of} />}
      </div>
      <ul className="flex flex-wrap gap-4 text-xs text-slate-400 mt-2" aria-label="Key">
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block w-4 border-t-2" style={{ borderColor: WORTH }} />
          Worth <span className="text-slate-400">(history, then forecast)</span>
        </li>
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block w-4 border-t" style={{ borderColor: PAID_IN }} />
          Paid in
        </li>
      </ul>
      {series && (
        <table className="sr-only">
          <caption>Worth and paid in ahead</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">Worth</th><th scope="col">Paid in</th></tr></thead>
          <tbody>
            {tablePoints(series.forecast, p.months).map((r) => (
              <tr key={r.date}><td>{r.date}</td><td>{gbp(Number(r.worth))}</td><td>{gbp(Number(r.paid_in))}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

function Choices(p: InvestmentGraphViewProps) {
  const holdings = p.options
  const seg = (active: boolean) =>
    `${active ? 'seg-active' : 'seg'} min-h-[44px] sm:min-h-0 inline-flex items-center cursor-pointer has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent`
  return (
    <div className="space-y-3">
      <fieldset>
        <legend className="text-sm text-slate-300 mb-1.5">Look ahead</legend>
        <div className="flex flex-wrap gap-2">
          {LOOK_AHEAD.map((o) => (
            <label key={o.months} className={seg(p.months === o.months)}>
              <input type="radio" name="look-ahead" value={o.months} checked={p.months === o.months}
                onChange={() => p.onMonths(o.months)} className="sr-only" />
              <span className="hidden sm:inline">{o.label}</span>
              <span className="sm:hidden" aria-hidden="true">{o.short}</span>
              <span className="sr-only sm:hidden">{o.label}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend className="text-sm text-slate-300 mb-1.5">Which investment</legend>
        {/* Padding so the focus outline isn't clipped by the scroll box (ux on #217). */}
        <div className="flex gap-2 overflow-x-auto p-1 -m-1">
          <label className={`${seg(p.holdingId === null)} shrink-0`}>
            <input type="radio" name="which-investment" value="" checked={p.holdingId === null}
              onChange={() => p.onHolding(null)} className="sr-only" />
            All investments
          </label>
          {holdings.map((h) => (
            <label key={h.id} className={`${seg(p.holdingId === h.id)} shrink-0`}>
              <input type="radio" name="which-investment" value={h.id} checked={p.holdingId === h.id}
                onChange={() => p.onHolding(h.id)} className="sr-only" />
              {h.name}
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  )
}

function Chart({ points, today }: { points: ChartPoint[]; today: string }) {
  const now = Date.parse(today)
  const first = points[0]?.t ?? now
  const last = points[points.length - 1]?.t ?? now
  const ticks = [...new Set([first, now, now + (last - now) / 2, last])].filter((t) => t >= first && t <= last)
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={points}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="t" type="number" scale="time" domain={[first, last]} ticks={ticks}
          tickFormatter={(t) => axisLabel(Number(t), today)} fontSize={12} tickLine={false} axisLine={false} stroke="#94A3B8" />
        <YAxis tickFormatter={(v) => gbp0(v)} width={80} fontSize={12} tickLine={false} axisLine={false} stroke="#94A3B8" />
        <Tooltip content={<GraphTooltip />} />
        <ReferenceLine x={now} stroke="#94A3B8" strokeDasharray="2 2" label={{ value: 'Today', position: 'insideTop', fontSize: 11, fill: '#94A3B8' }} />
        <Line type="linear" dataKey="history" name="Worth" stroke={WORTH} strokeWidth={2.5} connectNulls isAnimationActive={false}
          dot={(props: { cx?: number; cy?: number; payload?: ChartPoint; index?: number }) =>
            props.payload?.entered
              ? <circle key={props.index} cx={props.cx} cy={props.cy} r={3.5} fill={WORTH} />
              : <g key={props.index} />} />
        <Line type="linear" dataKey="forecast" name="Worth (forecast)" stroke={WORTH} strokeWidth={2.5} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
        <Line type="linear" dataKey="paidIn" name="Paid in" stroke={PAID_IN} strokeWidth={1.5} dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** The Over time card's tooltip style (ux on #217): the date, then each shown line. */
function GraphTooltip({ active, payload, label }: { active?: boolean; payload?: { name?: string; value?: number; color?: string }[]; label?: number }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-card2 border border-white/10 rounded-xl shadow-pop p-3 text-sm">
      <div className="font-medium text-slate-200">
        {new Date(Number(label)).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
      </div>
      {payload.filter((p) => p.value != null).map((p) => (
        <div key={p.name} className="flex justify-between gap-4 text-slate-300">
          <span>{p.name}</span><span className="tnum">{gbp(Number(p.value))}</span>
        </div>
      ))}
    </div>
  )
}
