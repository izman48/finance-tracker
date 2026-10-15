/** The "Card payment" tick on planned items (T-12-4, ux T-12-1 O-1..O-5).
 *
 * A ticked planned expense pays a credit card. No card is chosen and nothing
 * is matched by name: in each pay window the API counts the larger of the
 * ticked items and the projected card bills, once. The overlap chip and the
 * nudge's figures come from the API; the browser only shows them.
 */

export function canBeCardPayment(direction: string, kind: string): boolean {
  return direction === 'expense' && kind !== 'installment_plan'
}

export interface PlannedForm {
  name: string
  direction: string
  kind: string
  startDate: string
  amount?: string
  cadence?: string
  total?: string
  installments?: number
  apr?: string | null
  fee?: string | null
  cardPayment: boolean
}

/** The POST /analytics/planned-items body for the add form. */
export function plannedBody(f: PlannedForm): Record<string, unknown> {
  const base: Record<string, unknown> = { name: f.name, direction: f.direction, kind: f.kind, start_date: f.startDate }
  if (f.kind === 'installment_plan') {
    Object.assign(base, {
      total_amount: Number(f.total),
      installments: f.installments,
      cadence: f.cadence,
      apr: f.apr ? Number(f.apr) : null,
      fee_amount: f.fee ? Number(f.fee) : null,
    })
  } else if (f.kind === 'recurring') {
    Object.assign(base, { amount: Number(f.amount), cadence: f.cadence })
  } else {
    Object.assign(base, { amount: Number(f.amount) })
  }
  base.is_card_payment = f.cardPayment && canBeCardPayment(f.direction, f.kind)
  return base
}

export const CARD_OVERLAP_NUDGE_PREFIX = 'card_payment_overlap'

export function isCardOverlapNudge(id: string): boolean {
  return id.startsWith(CARD_OVERLAP_NUDGE_PREFIX)
}

/** Cashflow's overlap nudge links to /commitments#card-payments, which focuses
 *  the first planned item the API marks as overlapping. */
export const CARD_OVERLAP_ANCHOR = 'card-payments'

export function firstOverlapId(items: { id: string; card_payment_overlap?: boolean }[]): string | null {
  return items.find((it) => it.card_payment_overlap)?.id ?? null
}
