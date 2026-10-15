/** The Forecast view of the Wealth graph (owner 2026-10-15): net worth up
 *  to today, then the dashed projection, on a real date axis so years are
 *  evenly spaced however far away the target is. */
import { Area, CartesianGrid, ComposedChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { gbp0 as gbp } from '../../lib/format'
import { NET_WORTH_COLOUR } from '../../lib/netWorthLines'
import { yearTicks, type ForecastRow } from '../../lib/netWorthChart'

const TARGET_COLOUR = '#2DD4A7'
const monthYear = (t: number) => new Date(t).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })

function ForecastTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-card2 border border-white/10 rounded-xl shadow-pop p-3 text-sm">
      <div className="font-medium text-slate-200">{monthYear(Number(label))}</div>
      {payload.map((p: any) => (
        <div key={p.name} className="text-slate-300 tnum">
          {p.name}: {gbp(Number(p.value))}
        </div>
      ))}
    </div>
  )
}

export default function ForecastChart({ rows, target }: { rows: ForecastRow[]; target: number | null }) {
  const start = rows[0]?.t ?? 0
  const end = rows[rows.length - 1]?.t ?? 0
  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={rows} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={[start, end]}
          ticks={yearTicks(start, end)}
          tickFormatter={(t) => String(new Date(t).getUTCFullYear())}
          fontSize={12}
          tickLine={false}
          axisLine={false}
        />
        <YAxis tickFormatter={(v) => gbp(v)} width={70} fontSize={12} tickLine={false} axisLine={false} />
        <Tooltip content={<ForecastTooltip />} />
        {target && (
          <ReferenceLine
            y={target}
            stroke={TARGET_COLOUR}
            strokeDasharray="4 4"
            label={{ value: 'target', position: 'insideTopLeft', fontSize: 11, fill: TARGET_COLOUR }}
          />
        )}
        <Area type="monotone" dataKey="Net worth" stroke={NET_WORTH_COLOUR} strokeWidth={2} fill="none" fillOpacity={0} />
        <Area
          type="monotone"
          dataKey="Projected"
          stroke={TARGET_COLOUR}
          strokeWidth={2}
          strokeDasharray="6 4"
          fill="none"
          fillOpacity={0}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
