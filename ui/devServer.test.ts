import { describe, expect, it } from 'vitest'
import { devServerHost } from './devServer'

// T-08-15 (sec): the dev server is reachable from this machine only, unless
// a developer explicitly opts in to their LAN.
describe('devServerHost', () => {
  it('binds 127.0.0.1 by default', () => {
    expect(devServerHost({})).toBe('127.0.0.1')
  })

  it('opens to the LAN only with VITE_DEV_LAN=1', () => {
    expect(devServerHost({ VITE_DEV_LAN: '1' })).toBe('0.0.0.0')
  })

  it.each(['0', 'true', 'yes', ''])('anything else (%j) stays local', (value) => {
    expect(devServerHost({ VITE_DEV_LAN: value })).toBe('127.0.0.1')
  })
})
