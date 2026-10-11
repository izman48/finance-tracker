import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import UpcomingLabel from './UpcomingLabel'
import type { Upcoming } from '../lib/upcoming'

// The label half of a coming-up row, shared by Home and Cashflow (ux spec 2, M1/M4).
const row = (over: Partial<Upcoming> = {}): Upcoming => ({
  key: 'p-1', label: 'Tax refund', amount: 1203, date: '2026-10-15', income: true, ...over,
})
const html = (u: Upcoming, linkMarker: boolean) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <UpcomingLabel item={u} linkMarker={linkMarker} />
    </MemoryRouter>,
  )
const text = (h: string) => h.replace(/<[^>]+>/g, '')

describe('UpcomingLabel', () => {
  it('Cashflow: the marker is a link to the change', () => {
    const h = html(row({ claudeAuditId: 'a1' }), true)
    expect(h).toContain('href="/changes#change-a1"')
  })

  it('Home: the marker is shown as plain text, never a link inside the card link', () => {
    const h = html(row({ claudeAuditId: 'a1' }), false)
    expect(h).not.toContain('<a')
    expect(h).toContain('chip-info')
    expect(text(h)).toContain('Changed by Claude')
  })

  it('every planned-income row says it is not counted, on Home and Cashflow (D1)', () => {
    for (const link of [true, false]) {
      expect(text(html(row({ plannedIncome: true }), link))).toContain(
        'Not counted in your safe to spend until it arrives.',
      )
    }
    expect(text(html(row({ plannedIncome: false, income: true }), false))).not.toContain('Not counted')
  })

  it('no marker when Claude did not change it', () => {
    expect(text(html(row(), false))).not.toContain('Changed by Claude')
  })
})

describe('UpcomingLabel late (L1)', () => {
  it('shows the warn chip and the expected/late line, no alarm red', () => {
    const h = html(row({ late: { expected: '2026-10-05', days: 5 }, income: true, plannedIncome: false }), true)
    expect(h).toMatch(/class="chip-warn[^"]*"[^>]*>Late</)
    expect(text(h)).toContain('Expected 5 Oct · 5 days late · Not counted until it arrives.')
    expect(h).not.toContain('text-neg')
  })
})
