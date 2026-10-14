import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PositionStrip from './PositionStrip'
import type { NetWorthPosition } from '../services/api'

// T-10-7b: net worth now subtracts liabilities, so the breakdown under the
// position strip must add up to it (synthetic figures).
const position = (over: Partial<NetWorthPosition> = {}): NetWorthPosition => ({
  as_of: '2026-10-14', net_worth: '6000', bank: '3000', assets: '12000', liabilities: '9000',
  since: '2026-01-01', changes: [], ...over,
})
const text = (p: NetWorthPosition) => renderToStaticMarkup(<PositionStrip position={p} />).replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'")

describe('PositionStrip breakdown', () => {
  it('subtracts what is owed on loans and finance, so the line adds up to net worth', () => {
    expect(text(position())).toContain("£3,000 in banks + £12,000 in assets you've added − £9,000 owed on loans and finance")
  })

  it('leaves the loans part out when nothing is owed', () => {
    const t = text(position({ liabilities: '0', net_worth: '15000' }))
    expect(t).toContain("£3,000 in banks + £12,000 in assets you've added")
    expect(t).not.toContain('owed on loans')
  })
})
