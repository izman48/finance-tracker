/** Demo mode's investment graph (T-11-8): GET /holdings/projection for the
 *  sample holdings, computed with the holding engine's arithmetic (effective
 *  annual monthly rate, contribution at each month end, rounded at output;
 *  totals rounded once), so it reconciles with the sample projection and the
 *  balance sheet. Synthetic figures only. */

export interface SampleHolding {
  id: string
  name: string
  asset_type: string
  value: number
  /** Own growth % a year. */
  growth: number
  /** The linked bill's monthly amount, or the asset's own. */
  monthly: number
  valuations: { date: string; value: number }[]
}

const round2 = (n: number) => Math.round(n * 100) / 100
const money = (n: number) => round2(n).toFixed(2)

/** The engine's monthly series from the value today (unrounded). */
export function engineSeries(value: number, growthPct: number, contribution: number, months: number): number[] {
  const r = (1 + growthPct / 100) ** (1 / 12) - 1
  const out = [value]
  let v = value
  for (let m = 1; m <= months; m++) {
    v = v * (1 + r) + contribution
    out.push(v)
  }
  return out
}

export function sampleInvestmentGraph(
  holdings: SampleHolding[], months: number, holdingId: string | null, monthDate: (m: number) => string, today: string,
) {
  const shown = holdingId ? holdings.filter((h) => h.id === holdingId) : holdings
  const exact = shown.map((h) => engineSeries(h.value, h.growth, h.monthly, months))
  const valueToday = shown.reduce((s, h) => s + h.value, 0)
  const contribution = shown.reduce((s, h) => s + h.monthly, 0)
  const total = Array.from({ length: months + 1 }, (_, m) => ({
    date: monthDate(m),
    worth: money(exact.reduce((s, series) => s + series[m], 0)),
    paid_in: money(valueToday + contribution * m),
  }))
  const thousand = (v: string) => String(Math.round(Number(v) / 1000) * 1000)
  const historyDates = [...new Set(shown.flatMap((h) => h.valuations.map((v) => v.date)))].sort()
  return {
    as_of: today,
    months,
    holdings: shown.map((h, i) => ({
      id: h.id, name: h.name, kind: h.asset_type,
      value_today: money(h.value), value_as_of: h.valuations[h.valuations.length - 1].date,
      growth_pct: money(h.growth), monthly_contribution: money(h.monthly),
      history: h.valuations.map((v) => ({ date: v.date, worth: money(v.value) })),
      forecast: exact[i].map((v, m) => ({ date: monthDate(m), worth: money(v), paid_in: money(h.value + h.monthly * m) })),
    })),
    total: {
      value_today: money(valueToday),
      monthly_contribution: money(contribution),
      // The total on each date any holding was valued: each holding's latest value by then.
      history: historyDates.map((d) => ({
        date: d,
        worth: money(shown.reduce((s, h) => {
          const before = h.valuations.filter((v) => v.date <= d)
          return s + (before.length ? before[before.length - 1].value : 0)
        }, 0)),
      })),
      forecast: total,
      answer: shown.length ? { months, worth_about: thousand(total[months].worth), paid_in: thousand(total[months].paid_in) } : null,
    },
  }
}
