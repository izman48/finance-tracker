/**
 * The budget bar with commitments coming up (T-24-5; spec nilu-s24-plan.md,
 * "Budget bar"). Every figure is the API's: `spent`, `coming_up.amount` and
 * `over_by_payday`. The only arithmetic here is the bar's widths, as
 * percentages of `scale = max(limit, spent + coming up)`. Labels are bank
 * text, rendered as text only.
 */
import type { Budget, ComingUpItem } from './budgets'
import { gbp } from './format'

export interface BarGeometry {
  /** Percentages of the bar's width. */
  fill: number
  segmentStart: number
  segment: number
  /** Where the limit sits, only when the scale is stretched past it. */
  marker: number | null
  pace: number
}

const pct = (part: number, whole: number) => (whole > 0 ? Math.min(Math.max(part / whole, 0), 1) * 100 : 0)
const coming = (b: Budget) => Number(b.coming_up?.amount ?? 0)

export function barGeometry(b: Budget): BarGeometry {
  const spent = Number(b.spent)
  const scale = Math.max(b.limit_pounds, spent + coming(b))
  const stretched = coming(b) > 0 && scale > b.limit_pounds
  const fill = pct(spent, scale)
  return {
    fill,
    segmentStart: fill,
    segment: Math.min(pct(coming(b), scale), 100 - fill),
    marker: stretched ? pct(b.limit_pounds, scale) : null,
    pace: pct(Number(b.pace_spent), scale),
  }
}

/** The largest commitment by amount (ties: earliest due), then "and N other(s)". */
function names(b: Budget): { lead: string; more: string } | null {
  const items = b.coming_up?.items ?? []
  if (coming(b) <= 0 || items.length === 0) return null
  const [first] = [...items].sort(
    (x: ComingUpItem, y: ComingUpItem) => Number(y.amount) - Number(x.amount) || x.due_date.localeCompare(y.due_date))
  const others = (b.coming_up?.commitment_count ?? 1) - 1
  const more = others <= 0 ? '' : ` and ${others} other${others === 1 ? '' : 's'}`
  return { lead: `${first.label}${more}`, more: others <= 0 ? `, ${b.coming_up?.instalment_count} more this cycle` : '' }
}

/** "£192.00 coming up: Meal kit, 3 more this cycle", or null with nothing coming. */
export function comingUpLine(b: Budget): string | null {
  const n = names(b)
  return n && `${gbp(coming(b))} coming up: ${n.lead}${n.more}`
}

/** "£86.00 over by payday", from the API's figure; null when it is £0. */
export function overByPaydayText(b: Budget): string | null {
  const opb = Number(b.over_by_payday ?? 0)
  return opb > 0 ? `${gbp(opb)} over by payday` : null
}

/** "Meal kit will take you £128.00 over": only at or over the limit, where it
 *  differs from "over by payday" (spec assumption 3). */
export function takesYouOverLine(b: Budget): string | null {
  const n = names(b)
  if (!n || Number(b.spent) < b.limit_pounds) return null
  return `${n.lead} will take you ${gbp(coming(b))} over`
}

/** Appended to the meter's accessible name, so the hatch is never the only cue. */
export function comingUpA11y(b: Budget): string | null {
  const n = names(b)
  if (!n) return null
  const over = overByPaydayText(b)
  return `${gbp(coming(b))} coming up from ${n.lead}${n.more}, not counted as spent${over ? `, ${over} if all are paid` : ''}`
}
