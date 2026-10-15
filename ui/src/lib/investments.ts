/**
 * Wealth > Investments and the investment graph (T-11-5; ux T-11-2).
 * Investments are owner D1's kinds: ISA, investment, pension, crypto. Every
 * forecast figure comes from GET /holdings/projection (the holding engine,
 * the same function as the target projection); the browser sums nothing
 * except the balance sheet's own latest values. Pure helpers, so each
 * sentence is tested.
 */
import type { Asset } from '../services/api'
import { latestValue } from './assets'
import { gbp, gbp0 } from './format'

export const INVESTMENT_TYPES = ['isa', 'investment', 'pension', 'crypto'] as const
export const isInvestment = (assetType: string) => (INVESTMENT_TYPES as readonly string[]).includes(assetType)

/** Type names in the Investments group and its form (ux "Words"). */
export const INVESTMENT_TYPE_LABEL: Record<string, string> = {
  isa: 'ISA', investment: 'Investment', pension: 'Pension', crypto: 'Crypto',
}

/** The look-ahead choices on the graph. */
export const LOOK_AHEAD = [
  { months: 60, label: '5 years', short: '5y' },
  { months: 120, label: '10 years', short: '10y' },
  { months: 240, label: '20 years', short: '20y' },
  { months: 360, label: '30 years', short: '30y' },
] as const

type Money = string

export interface GraphHistoryPoint { date: string; worth: Money }
export interface GraphForecastPoint { date: string; worth: Money; paid_in: Money }
export interface InvestmentSeries {
  id: string
  name: string
  kind: string
  value_today: Money
  value_as_of: string
  growth_pct: Money
  monthly_contribution: Money
  history: GraphHistoryPoint[]
  forecast: GraphForecastPoint[]
}
export interface GraphAnswer { months: number; worth_about: Money; paid_in: Money }
export interface InvestmentGraph {
  as_of: string
  months: number
  holdings: InvestmentSeries[]
  total: {
    value_today: Money
    monthly_contribution: Money
    history: GraphHistoryPoint[]
    forecast: GraphForecastPoint[]
    answer: GraphAnswer | null
  }
}

/** Whole pounds without pence, pence kept when there are any. */
const pounds = (n: number) => (Number.isInteger(n) ? gbp0(n) : gbp(n))
const pct = (s: string) => `${Number(s)}%`

/** The monthly contribution: the linked bill's amount, else the asset's own. */
export function contributionOf(asset: Asset): number {
  const linked = asset.linked_commitment?.amount
  return Number(linked ?? asset.monthly_contribution ?? 0)
}

/** Row line 2: `ISA · 7% a year · £1,000 a month`. */
export function investmentLine(asset: Asset): string {
  const type = INVESTMENT_TYPE_LABEL[asset.asset_type] ?? asset.asset_type
  const contribution = contributionOf(asset)
  if (asset.assumed_growth_pct == null) {
    return contribution > 0 ? `${type} · growth not set · ${pounds(contribution)} a month` : `${type} · growth not set`
  }
  const monthly = contribution > 0 ? `${pounds(contribution)} a month` : 'no monthly contribution'
  return `${type} · ${pct(asset.assumed_growth_pct)} a year · ${monthly}`
}

/** The Investments group's figure: the latest value of each investment. */
export const investmentsTotal = (assets: Asset[]) =>
  assets.filter((a) => isInvestment(a.asset_type)).reduce((s, a) => s + latestValue(a), 0)

/** `In 10 years: worth about £171,000, paid in £120,000` (the API rounds). */
export function answerSentence(answer: GraphAnswer | null): string {
  if (!answer) return ''
  const years = answer.months / 12
  return `In ${years} years: worth about ${gbp0(Number(answer.worth_about))}, paid in ${gbp0(Number(answer.paid_in))}`
}

/** One holding: `£0 today, £1,000 a month, 7% a year.`; all of them:
 *  `2 investments, £28,000 today, £1,000 a month.` (the API's totals). */
export function inputsLine(graph: InvestmentGraph, holdingId: string | null): string {
  if (holdingId) {
    const h = graph.holdings.find((x) => x.id === holdingId)
    if (!h) return ''
    return `${pounds(Number(h.value_today))} today, ${pounds(Number(h.monthly_contribution))} a month, ${pct(h.growth_pct)} a year.`
  }
  const n = graph.holdings.length
  return `${n} ${n === 1 ? 'investment' : 'investments'}, ${pounds(Number(graph.total.value_today))} today, ${pounds(Number(graph.total.monthly_contribution))} a month.`
}

/** Which notes show under the inputs line (ux states G-5, G-6). */
export function graphStateNotes(graph: InvestmentGraph, holdingId: string | null) {
  const series = holdingId ? graph.holdings.find((x) => x.id === holdingId) : null
  const history = series ? series.history : graph.total.history
  return {
    historyStarts: history.length <= 1,
    flat: !!series && Number(series.growth_pct) === 0,
  }
}

export interface ChartPoint {
  date: string
  /** The date as a timestamp, for a time-scaled axis. */
  t: number
  /** A valuation was entered on this date (draw a dot). */
  entered?: boolean
  /** An entered value (a dot on the solid history line). */
  history?: number
  /** The forecast (dashed), from today. */
  forecast?: number
  paidIn?: number
}

/** One row per date: entered valuations, then the forecast from today. The
 *  today point carries both, so the dashed line starts where the solid one
 *  ends; nothing is drawn between valuations except straight segments. */
export function chartPoints(series: { history: GraphHistoryPoint[]; forecast: GraphForecastPoint[] }): ChartPoint[] {
  const byDate = new Map<string, ChartPoint>()
  for (const h of series.history) byDate.set(h.date, { date: h.date, t: Date.parse(h.date), history: Number(h.worth), entered: true })
  series.forecast.forEach((f, i) => {
    const point = byDate.get(f.date) ?? { date: f.date, t: Date.parse(f.date) }
    // Today's point also ends the solid line, at the value today.
    const history = i === 0 && series.history.length ? (point.history ?? Number(f.worth)) : point.history
    byDate.set(f.date, { ...point, history, forecast: Number(f.worth), paidIn: Number(f.paid_in) })
  })
  return [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
}

/** The visually hidden table's rows: 1, 5, 10, 20 and 30 years, within the range. */
export function tablePoints(forecast: GraphForecastPoint[], months: number): GraphForecastPoint[] {
  return [12, 60, 120, 240, 360].filter((m) => m <= months && m < forecast.length).map((m) => forecast[m])
}

/** The growth % for holdings with none of their own: the target form's
 *  (`wealth.growth`), as the projection uses it, else 5% (the API default). */
export function graphDefaultGrowth(raw: string | null): number {
  const n = raw == null || raw.trim() === '' ? NaN : Number(raw)
  return Number.isFinite(n) && n >= -100 && n <= 50 ? n : 5
}

/** `Test ISA. Last value £18,000, 10 days ago.` (ux "Update value"). */
export function lastValueLine(asset: Asset, now: number): string {
  const last = asset.valuations[asset.valuations.length - 1]
  if (!last) return `${asset.name}.`
  const days = Math.max(0, Math.floor((now - new Date(`${last.valued_at}T00:00:00Z`).getTime()) / 86400000))
  const ago = days === 0 ? 'today' : days === 1 ? '1 day ago' : `${days} days ago`
  return `${asset.name}. Last value ${pounds(Number(last.value))}, ${ago}.`
}

/** The value typed in: 0 to 10,000,000 (the API's bound), commas allowed. */
export function parseValueToday(raw: string): number | null {
  const s = raw.trim().replace(/,/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null
  const n = Number(s)
  return n <= 10_000_000 ? n : null
}

const DAY = 86400000
/** Whole days since the latest valuation. */
export const daysSinceValued = (asset: Asset, now: number) => {
  const last = asset.valuations[asset.valuations.length - 1]
  return last ? Math.max(0, Math.floor((now - new Date(`${last.valued_at}T00:00:00Z`).getTime()) / DAY)) : null
}

/** `updated 10 days ago` under a row's value (ux "Words"). */
export function updatedAgo(days: number): string {
  if (days === 0) return 'updated today'
  if (days === 1) return 'updated 1 day ago'
  if (days < 60) return `updated ${days} days ago`
  const months = Math.round(days / 30.44)
  if (months < 24) return `updated ${months} months ago`
  return `updated ${Math.round(days / 365)} years ago`
}

/** A value older than this shows Update value as a warning (ux). */
export const STALE_VALUE_DAYS = 30

const YEAR_MS = 365.25 * 86400000
/** x-axis ticks (ux "Words"): `Today`, `+5y` ahead, `Apr 2026` before. */
export function axisLabel(t: number, today: string): string {
  const now = Date.parse(today)
  if (Math.abs(t - now) < 86400000) return 'Today'
  if (t > now) return `+${Math.round((t - now) / YEAR_MS)}y`
  return new Date(t).toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}
