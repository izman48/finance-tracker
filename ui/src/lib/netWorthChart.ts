/** The Wealth graph's two views (owner 2026-10-15).
 *
 * History draws the chosen range with its group lines across the full
 * width. Forecast, offered once a target gives a projection, draws net
 * worth to today and the projection after it on a real date axis, so a
 * 20-year forecast never squeezes the history lines into the left edge. */

export type ChartView = 'history' | 'forecast'
export const VIEW_KEY = 'wealth.chartView'

/** Forecast is the default whenever there is one; History only when chosen. */
export function parseView(raw: string | null, hasForecast: boolean): ChartView {
  if (!hasForecast) return 'history'
  return raw === 'history' ? 'history' : 'forecast'
}

export interface ForecastRow {
  t: number
  'Net worth'?: number
  Projected?: number
}

const time = (date: string) => new Date(date).getTime()

/** Rows keyed by timestamp: history as "Net worth", then the projection as
 *  "Projected". Today is in both (the projection's first point is today),
 *  so the solid line and the dashed one meet. */
export function forecastRows(
  history: { date: string; net_worth: string }[],
  timeline: { date: string; value: string }[],
): ForecastRow[] {
  if (!history.length || !timeline.length) return []
  const past: ForecastRow[] = history.map((p) => ({ t: time(p.date), 'Net worth': Number(p.net_worth) }))
  past[past.length - 1].Projected = past[past.length - 1]['Net worth']
  return [...past, ...timeline.slice(1).map((p) => ({ t: time(p.date), Projected: Number(p.value) }))]
}

/** A few 1 January ticks, evenly spaced in whole years, inside [start, end];
 *  the two ends when the range holds no 1 January. */
export function yearTicks(start: number, end: number): number[] {
  const startDate = new Date(start)
  const first = startDate.getUTCFullYear() + (start > Date.UTC(startDate.getUTCFullYear(), 0, 1) ? 1 : 0)
  const last = new Date(end).getUTCFullYear()
  if (first > last) return [start, end]
  const step = Math.max(1, Math.ceil((last - first) / 3))
  const ticks: number[] = []
  for (let y = first; y <= last; y += step) ticks.push(Date.UTC(y, 0, 1))
  return ticks
}
