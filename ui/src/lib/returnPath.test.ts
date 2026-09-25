import { describe, it, expect } from 'vitest'
import { safeReturnPath } from './returnPath'

describe('safeReturnPath — where login sends you back to', () => {
  it('returns an in-app path with its query intact', () => {
    expect(safeReturnPath({ pathname: '/oauth/authorize', search: '?client_id=a&state=b' })).toBe(
      '/oauth/authorize?client_id=a&state=b',
    )
  })

  it('defaults to Home when there is nowhere to return to', () => {
    expect(safeReturnPath(undefined)).toBe('/home')
    expect(safeReturnPath(null)).toBe('/home')
    expect(safeReturnPath({})).toBe('/home')
  })

  it('never leaves the site', () => {
    // Protocol-relative and backslash tricks resolve to another origin.
    expect(safeReturnPath({ pathname: '//evil.example/x' })).toBe('/home')
    expect(safeReturnPath({ pathname: '/\\evil.example' })).toBe('/home')
    expect(safeReturnPath({ pathname: 'https://evil.example' })).toBe('/home')
  })

  it('does not bounce back to the auth pages', () => {
    expect(safeReturnPath({ pathname: '/login' })).toBe('/home')
  })
})
