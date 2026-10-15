import { afterAll, beforeAll, describe, expect, it } from 'vitest'

// sec T-11-8: in demo ("Anonymize numbers") mode, real figures never reach
// the new surfaces and no write leaves the browser. The real API is stubbed
// to answer every request with a sentinel; the test first proves the
// sentinel is served when demo mode is off, so its absence means something.
const SENTINEL = '987654.32'
const store = new Map<string, string>()
const stubStorage = {
  getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k), clear: () => store.clear(), key: () => null, length: 0,
}

let api: typeof import('./api')
let anonymize: typeof import('../lib/anonymize')
const network: string[] = []

beforeAll(async () => {
  Object.defineProperty(globalThis, 'localStorage', { value: stubStorage, configurable: true })
  api = await import('./api')
  anonymize = await import('../lib/anonymize')
  const sentinelEverywhere = { value_today: SENTINEL, total: { value_today: SENTINEL }, net_worth: SENTINEL, holdings: [{ value_today: SENTINEL }] }
  api.default.defaults.adapter = async (config) => {
    network.push(`${(config.method ?? 'get').toUpperCase()} ${config.url}`)
    return { data: sentinelEverywhere, status: 200, statusText: 'OK', headers: {}, config }
  }
})
afterAll(() => anonymize.setAnonymized(false))

const reads = () => [
  api.holdingsAPI.projection({ months: 120 }),
  api.holdingsAPI.projection({ months: 120, holding_id: 'sas1' }),
  api.assetsAPI.list(),
  api.assetsAPI.netWorthHistory(12),
  api.assetsAPI.netWorthPosition(),
  api.assetsAPI.netWorthProjection({ monthly_contribution: 0 }),
  api.analyticsAPI.getSummary(),
]

describe('demo mode never shows real holdings or writes to the real account', () => {
  it('precondition: with demo mode off, the stubbed API serves the sentinel', async () => {
    const res = await api.holdingsAPI.projection({ months: 120 })
    expect(JSON.stringify(res.data)).toContain(SENTINEL)
    expect(network.length).toBe(1)
  })

  it('with demo mode on, no new surface shows the sentinel and nothing reaches the API', async () => {
    anonymize.setAnonymized(true)
    network.length = 0
    const bodies = await Promise.all(reads())
    for (const res of bodies) expect(JSON.stringify(res.data)).not.toContain(SENTINEL)
    expect(bodies.map((r) => JSON.stringify(r.data).length).every((len) => len > 2)).toBe(true) // sample data, not {}
    expect(network).toEqual([])
  })

  it('with demo mode on, Update value, add, edit, link, unlink and delete are blocked before the network', async () => {
    anonymize.setAnonymized(true)
    network.length = 0
    const writes = [
      api.assetsAPI.addValuation('sas1', { value: 1 }),
      api.assetsAPI.create({ name: 'x', asset_type: 'isa', value: 1 }),
      api.assetsAPI.update('sas1', { assumed_growth_pct: 3 }),
      api.assetsAPI.setContribution('sas1', { amount: '1.00', next_date: '2026-10-28' }),
      api.assetsAPI.stopContribution('sas1'),
      api.assetsAPI.remove('sas1'),
    ]
    const results = await Promise.allSettled(writes)
    expect(results.every((r) => r.status === 'rejected')).toBe(true)
    expect(network).toEqual([])
  })
})
