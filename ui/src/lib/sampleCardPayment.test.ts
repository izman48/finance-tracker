import { describe, expect, it } from 'vitest'
import { sampleResponse } from './sampleAccount'
import type { PlannedItem } from '../types'

const get = <T,>(path: string, params: Record<string, unknown> = {}) => sampleResponse(`/api/v1${path}`, params) as T
const gbp2 = (n: number) => `£${n.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

describe('demo: a planned card payment overlapping the projected card bill (T-12-7a, ux demo, sec T-12-4)', () => {
  const planned = get<PlannedItem[]>('/analytics/planned-items')
  const summary = get<{ next_payday: string; next_repayments: { amount: number; due_date: string }[] }>('/analytics/summary')
  const today = new Date().toISOString().slice(0, 10)
  const inWindow = (d: string) => d >= today && d < summary.next_payday

  it('has a ticked "Card bill" the API would mark as overlapping', () => {
    const bill = planned.find((p) => p.name === 'Card bill')!
    expect(bill).toMatchObject({ direction: 'expense', kind: 'one_off', is_card_payment: true, card_payment_overlap: true })
    expect(inWindow(bill.start_date)).toBe(true)
  })

  it("the nudge's figures come from the sample by the API's rule: the larger counts once", () => {
    const manual = planned.filter((p) => p.is_card_payment && inWindow(p.start_date)).reduce((s, p) => s + Number(p.amount), 0)
    // The projected side: the card bills and the card plan instalments (T-12-5b) in the window.
    const forecast = get<{ timeline: { date: string; events: { kind: string; label: string; amount: number }[] }[] }>('/analytics/forecast', { horizon: '30' })
    const instalments = forecast.timeline.filter((d) => inWindow(d.date))
      .flatMap((d) => d.events.filter((e) => e.kind === 'repayment' && e.label.endsWith(' instalment')))
      .reduce((s, e) => s - e.amount, 0)
    const projected = summary.next_repayments.filter((r) => inWindow(r.due_date)).reduce((s, r) => s + r.amount, 0) + instalments
    const nudge = get<{ id: string; body: string }[]>('/analytics/nudges').find((n) => n.id.startsWith('card_payment_overlap'))!
    expect(nudge.body).toBe(
      `Your planned card payments (${gbp2(manual)}) overlap your projected card bills (${gbp2(projected)}). ` +
      `nilu counts the larger, ${gbp2(Math.max(manual, projected))}, once.`,
    )
    // Anchored on the day before payday, as the API does.
    const eve = new Date(`${summary.next_payday}T00:00:00Z`)
    eve.setUTCDate(eve.getUTCDate() - 1)
    expect(nudge.id).toBe(`card_payment_overlap_${eve.toISOString().slice(0, 10)}`)
  })

  it('the manual payment is smaller, so the forecast and safe-to-spend are as before (no planned event added)', () => {
    const f = get<{ timeline: { events: { label: string }[] }[] }>('/analytics/forecast', { horizon: 'payday' })
    expect(f.timeline.flatMap((p) => p.events).some((e) => e.label === 'Card bill')).toBe(false)
  })
})
