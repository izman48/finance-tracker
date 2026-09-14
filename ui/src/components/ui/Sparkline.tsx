import { Area, AreaChart, Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip } from 'recharts'

export interface SparkPoint {
  label: string
  value: number
}

function SparkTooltip({ active, payload, format }: any) {
  if (!active || !payload?.length) return null
  const p: SparkPoint = payload[0].payload
  return (
    <div className="bg-card2 border border-white/10 rounded-xl shadow-pop px-2.5 py-1.5 text-xs">
      <span className="text-slate-400">{p.label}</span>{' '}
      <span className="text-slate-100 tnum font-medium">{format(p.value)}</span>
    </div>
  )
}

/**
 * A no-axes miniature of a tab's main chart, for summary cards. Same colours
 * as the full chart it stands in for, so the card and the tab read as one
 * thing. `highlightLast` (bars) picks out the current period.
 */
export default function Sparkline({
  data,
  kind = 'area',
  color = '#2DD4A7',
  height = 64,
  format,
  zeroLine = false,
  highlightLast = false,
}: {
  data: SparkPoint[]
  kind?: 'area' | 'bars'
  color?: string
  height?: number
  format: (n: number) => string
  /** Draw the £0 line when the series crosses it (a forecast dipping under). */
  zeroLine?: boolean
  highlightLast?: boolean
}) {
  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center text-xs text-slate-600" style={{ height }}>
        Not enough history yet
      </div>
    )
  }
  const crossesZero = zeroLine && data.some((d) => d.value < 0) && data.some((d) => d.value > 0)
  const gradientId = `spark-${color.replace('#', '')}`

  return (
    <ResponsiveContainer width="100%" height={height}>
      {kind === 'bars' ? (
        <BarChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }} barCategoryGap="25%">
          <Tooltip content={<SparkTooltip format={format} />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {data.map((_, i) => (
              <Cell
                key={i}
                fill={color}
                fillOpacity={highlightLast && i !== data.length - 1 ? 0.35 : 1}
              />
            ))}
          </Bar>
        </BarChart>
      ) : (
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.3} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Tooltip content={<SparkTooltip format={format} />} cursor={{ stroke: 'rgba(255,255,255,0.15)' }} />
          {crossesZero && <ReferenceLine y={0} stroke="#475569" strokeWidth={1} />}
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#${gradientId})`}
            isAnimationActive={false}
          />
        </AreaChart>
      )}
    </ResponsiveContainer>
  )
}
