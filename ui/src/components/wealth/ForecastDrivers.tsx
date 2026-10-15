/** Under the Forecast graph: the monthly figures the projection is built
 *  from, so commitments, budgets and contributions are visible, adding up
 *  to net worth's monthly change before growth (owner 2026-10-15). */
import { gbp0 as gbp } from '../../lib/format'
import type { ForecastDrivers as Drivers } from '../../lib/forecastDrivers'

function signed(value: number) {
  if (value === 0) return gbp(0) // a move (T-12-0): plain £0, never "+£0"
  return value < 0 ? `−${gbp(Math.abs(value))}` : `+${gbp(value)}`
}

const tone = (value: number) => (value === 0 ? 'text-slate-200' : value < 0 ? 'text-slate-300' : 'text-accent')

export default function ForecastDrivers({ drivers }: { drivers: Drivers }) {
  return (
    <section aria-labelledby="forecast-drivers-heading" className="mt-4">
      <h3 id="forecast-drivers-heading" className="text-xs uppercase tracking-wider text-slate-400 mb-1.5">
        What moves it each month
      </h3>
      <ul className="divide-y divide-white/[0.05]">
        {drivers.rows.map((row) => (
          <li key={row.label} className="flex items-center gap-3 min-h-[44px] px-1">
            <span className="flex-1 min-w-0">
              <span className="block text-slate-300">{row.label}</span>
              <span className="block text-xs text-slate-400">{row.detail}</span>
            </span>
            <span className={`tnum shrink-0 ${tone(row.amount)}`}>{signed(row.amount)}</span>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-3 min-h-[44px] px-1 border-t border-white/10">
        <span className="flex-1 min-w-0 text-slate-100 font-medium">Net worth change before growth</span>
        <span className="tnum shrink-0 text-slate-50 font-medium">{signed(drivers.total)} a month</span>
      </div>
      <p className="text-xs text-slate-400 px-1">
        Plus {drivers.growthPct}% a year growth on what is invested.
        {drivers.notes.map((n) => ` ${n}`).join('')}
      </p>
    </section>
  )
}
