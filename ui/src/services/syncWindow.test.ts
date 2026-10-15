import { describe, expect, it, vi } from 'vitest'
import api, { bankingAPI, SYNC_WINDOW_DAYS } from './api'

// T-12-12: after the first sync the API fetches only the last 88 days (its
// FALLBACK_DAYS), so the UI asks for exactly that, never 365 or 1825.
describe('transaction sync window', () => {
  it('asks for the 88 days the API serves', async () => {
    expect(SYNC_WINDOW_DAYS).toBe(88)
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} })
    let sent: unknown = null
    const before = api.defaults.adapter
    api.defaults.adapter = async (cfg) => {
      sent = JSON.parse(String(cfg.data))
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config: cfg }
    }
    try {
      await bankingAPI.syncTransactions()
    } finally {
      api.defaults.adapter = before
      vi.unstubAllGlobals()
    }
    expect(sent).toEqual({ days: 88 })
  })
})
