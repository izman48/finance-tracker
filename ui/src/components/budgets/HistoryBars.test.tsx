import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import HistoryBars, { type HistoryBar } from './HistoryBars'

// The History bar charts (concept 14; BH5, BH8, BH9, BH11). Static markup.
const bar = (over: Partial<HistoryBar> = {}): HistoryBar => ({
  key: 'a', label: '2 Aug to 29 Aug: spent £276 of £300, within your limit', kind: 'within', value: 276, limit: 300, ...over,
})
const html = (bars: HistoryBar[], ticks = false) => renderToStaticMarkup(<HistoryBars bars={bars} height={40} ticks={ticks} />)

describe('HistoryBars', () => {
  it('BH11: every bar is named by its sentence', () => {
    const h = html([bar(), bar({ key: 'b', label: 'X: paused, not counted', kind: 'paused', value: 0, limit: null })])
    expect(h).toContain('role="img" aria-label="2 Aug to 29 Aug: spent £276 of £300, within your limit"')
    expect(h).toContain('aria-label="X: paused, not counted"')
  })

  it('BH8: an over bar is outlined, never the neg red; within is filled', () => {
    const over = html([bar({ kind: 'over', value: 318 })])
    expect(over).toContain('data-kind="over"')
    expect(over).toMatch(/data-kind="over"[^>]*class="[^"]*border/)
    expect(over).not.toMatch(/neg/)
    expect(html([bar()])).toMatch(/data-kind="within"[^>]*class="[^"]*bg-accent/)
  })

  it('BH5/BH9: paused is a dashed slot, Now is hatched, an empty slot draws nothing', () => {
    expect(html([bar({ kind: 'paused', value: 0, limit: null })])).toMatch(/data-kind="paused"[^>]*class="[^"]*border-dashed/)
    expect(html([bar({ kind: 'now', value: 120, limit: null })])).toContain('repeating-linear-gradient')
    expect(html([bar({ kind: 'empty', value: 0, limit: null })])).toMatch(/data-kind="empty"[^>]*style="height:0%"/)
  })

  it('each cycle draws its own dashed limit line', () => {
    const h = html([bar({ limit: 300 }), bar({ key: 'b', limit: 250, value: 100 })])
    expect((h.match(/data-limit/g) ?? []).length).toBe(2)
    expect(h).toMatch(/border-dashed/)
  })

  it('tick labels only when asked, and hidden from screen readers (the bar names carry the dates)', () => {
    expect(html([bar({ tick: '2 Aug' })], true)).toMatch(/aria-hidden="true"[^>]*>.*2 Aug/)
    expect(html([bar({ tick: '2 Aug' })], false)).not.toContain('>2 Aug<')
  })
})
