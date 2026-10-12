import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import HistoryView, { type HistoryViewProps } from './HistoryView'
import type { HistoryBudget, HistoryCycle, HistoryResponse, HistorySlot } from '../../lib/budgetHistory'

// Spending > Budgets > Past cycles (concept 14; BH1-BH14). Static markup.
const starts = ['2026-04-12', '2026-05-10', '2026-06-07', '2026-07-05', '2026-08-02', '2026-08-30']
const ends = ['2026-05-09', '2026-06-06', '2026-07-04', '2026-08-01', '2026-08-29', '2026-09-26']
const cycles: HistoryCycle[] = starts.map((start, i) => ({
  start, end: ends[i], total_limit: '450', total_spent: i === 3 ? '480' : '420', on_target: i !== 3,
}))
const spends = [276, 291, 262, 310, 318, 285]
const slots: HistorySlot[] = starts.map((start, i) => ({
  start, end: ends[i], existed: true, paused: false, limit_pounds: 300, spent: String(spends[i]), kept: spends[i] <= 300,
}))
const groceries: HistoryBudget = { budget_id: 'g', category: 'Groceries', kept: 4, counted: 6, usually: '290.33', cycles: slots }
const data = (over: Partial<HistoryResponse> = {}): HistoryResponse => ({
  cycles, budgets: [groceries], on_target: 5, counted: 6, trend: { difference: '42', direction: 'lower' }, has_more: true, ...over,
})
const props = (over: Partial<HistoryViewProps> = {}): HistoryViewProps => ({
  status: 'ready', data: data(), now: { start: '2026-09-27', end: '2026-10-24', spent: 212 }, more: 'idle',
  retrying: false, onRetry: () => {}, onShowMore: () => {}, ...over,
})
const html = (over: Partial<HistoryViewProps> = {}) => renderToStaticMarkup(<HistoryView {...props(over)} />)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('HistoryView', () => {
  it('BH1/BH6: the headline, helper, caption and trend, readable without the chart', () => {
    const t = text(html())
    expect(t).toContain('On target in 5 of the last 6 cycles')
    expect(t).toContain('A cycle is on target when your budgeted spending stays within the total of your limits.')
    expect(t).toContain('Dashed line = your limits. Outlined bar = went over. Each bar uses the limits that applied in that cycle.')
    expect(t).toContain('Your budgeted spending is about £42 a cycle lower than in the 3 cycles before.')
  })

  it('BH2: per budget, the limit, usually and Kept k of n', () => {
    const t = text(html())
    expect(t).toContain('Groceries')
    expect(t).toContain('Limit £300 · usually £290.33')
    expect(t).toContain('Kept 4 of 6')
  })

  it('BH9/BH14: a hatched Now bar, named without an amount, after the completed cycles', () => {
    const h = html()
    expect(h).toContain('aria-label="27 Sept to now: this cycle, still running, not counted"')
    expect(h.indexOf('data-kind="now"')).toBeGreaterThan(h.indexOf('26 Sept: spent'))
  })

  it('BH11: a visually hidden table is the full alternative', () => {
    const h = html()
    expect(h).toMatch(/<table class="sr-only"/)
    expect(text(h)).toContain('5 Jul to 1 Aug £450 £480 Over')
  })

  it('BH8: no failed, missed or streak; no neg red', () => {
    const h = html()
    expect(h).not.toMatch(/failed|missed|streak/i)
    expect(h).not.toMatch(/text-neg|bg-neg/)
  })

  it('BH7: no completed cycle: the empty state, no chart', () => {
    const t = text(html({ data: data({ cycles: [], budgets: [], on_target: 0, counted: 0, trend: null, has_more: false }) }))
    expect(t).toContain('History appears after your first full pay cycle')
    expect(t).toContain('When this cycle ends on 24 Oct it will show here, and builds up to the last 6 cycles.')
    expect(html({ data: data({ cycles: [], budgets: [], counted: 0, has_more: false }) })).not.toContain('role="img"')
  })

  it('BH10/BH14: Show more while the server has more; Loading…; the older-page error keeps the cycles', () => {
    expect(text(html())).toContain('Show more cycles')
    expect(text(html({ data: data({ has_more: false }) }))).not.toContain('Show more cycles')
    expect(text(html({ more: 'loading' }))).toContain('Loading…')
    const err = html({ more: 'error' })
    expect(err).toMatch(/role="alert"[^>]*>Couldn&#x27;t load older cycles\. Try again\./)
    expect(text(err)).toContain('On target in 5 of the last 6 cycles')
  })

  it('load error: our own sentence and Try again; loading: a skeleton', () => {
    const t = text(html({ status: 'error', data: null }))
    expect(t).toContain("Couldn't load your budget history. Your spending is unaffected. Try again.")
    expect(t).toContain('Try again')
    expect(html({ status: 'loading', data: null })).toContain('Loading budget history…')
  })

  it('BH13: paused throughout, and every cycle paused', () => {
    const paused = { ...groceries, kept: 0, counted: 0, usually: null }
    const t = text(html({ data: data({ budgets: [paused], on_target: 0, counted: 0, trend: null }) }))
    expect(t).toContain('Paused in these cycles')
    expect(t).not.toContain('Kept 0 of 0')
    expect(t).toContain('No cycles counted yet: your budgets were paused.')
  })

  it('BH12: a category with markup is text', () => {
    const h = html({ data: data({ budgets: [{ ...groceries, category: '<img src=x onerror=alert(1)>' }] }) })
    expect(h).not.toContain('<img src=x')
    expect(h).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })
})
