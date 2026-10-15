/** The net worth graph's groups and line choices (T-11-6, ux T-11-2).
 *
 * The API gives each history point Cash, Investments, Property and Debt,
 * which add up to its net worth. The browser only shows them: showing or
 * hiding a line never changes a figure (N-2). Line choices and "Include
 * investments" live in this browser only (A6). */
import type { NetWorthPoint } from '../services/api'

export type GroupKey = 'cash' | 'investments' | 'property' | 'debt'

export const GROUPS: { key: GroupKey; label: string; colour: string }[] = [
  { key: 'cash', label: 'Cash', colour: '#34D399' },
  { key: 'investments', label: 'Investments', colour: '#A78BFA' },
  { key: 'property', label: 'Property & other', colour: '#F472B6' },
  { key: 'debt', label: 'Debt', colour: '#FBBF24' },
]
export const NET_WORTH_COLOUR = '#38BDF8'
export const LINES_KEY = 'wealth.lines'
export const INCLUDE_KEY = 'wealth.includeInvestments'

const KNOWN = new Set<string>(GROUPS.map((g) => g.key))

export interface KeyRow {
  key: GroupKey
  label: string
  colour: string
  /** Signed as shown: Debt is negative. */
  value: number
  /** False only for Investments when the box is unticked ("Not included"). */
  included: boolean
}

function figure(point: NetWorthPoint, key: GroupKey): number {
  const value = Number(point[key] ?? 0)
  return key === 'debt' ? -value : value
}

/** The key under the chart, from today's point. A group at 0 is left out
 *  (N-7); Debt shows whenever anything is owed (A5). */
export function keyRows(point: NetWorthPoint, includeInvestments: boolean): KeyRow[] {
  return GROUPS.filter((g) => figure(point, g.key) !== 0).map((g) => ({
    ...g,
    value: figure(point, g.key),
    included: g.key !== 'investments' || includeInvestments,
  }))
}

export function headline(includeInvestments: boolean): string {
  return includeInvestments ? 'Total net worth' : 'Net worth without investments'
}

/** Stored line choices: known group keys only; anything else is the default (N-11). */
export function parseLines(raw: string | null): GroupKey[] {
  try {
    const value: unknown = JSON.parse(raw ?? '[]')
    return Array.isArray(value) ? (value.filter((k) => typeof k === 'string' && KNOWN.has(k)) as GroupKey[]) : []
  } catch {
    return []
  }
}

export function parseIncludeInvestments(raw: string | null): boolean {
  return raw !== 'false'
}

/** One chart row per point with net worth and every group, so toggling a
 *  line only changes what is drawn. */
export function chartRows(points: NetWorthPoint[], label: (date: string) => string) {
  return points.map((p) => ({
    date: label(p.date),
    'Net worth': Number(p.net_worth),
    ...Object.fromEntries(GROUPS.map((g) => [g.label, figure(p, g.key)])),
  }))
}
