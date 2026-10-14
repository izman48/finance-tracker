import { describe, it, expect } from 'vitest'
import apiSource from '../services/api.ts?raw'
import { sampleResponse, UNSAMPLED_BY_DESIGN, KNOWN_DEMO_GAPS } from './sampleAccount'

// Demo mode ("Anonymize numbers") serves every read from the sample account
// and answers anything it doesn't recognise with {}. A new feature whose GET
// isn't taught to sampleResponse silently shows nothing in demo mode (that is
// how budgets went missing). So every GET the UI makes must either be served,
// or be listed, with a reason, in UNSAMPLED_BY_DESIGN or KNOWN_DEMO_GAPS.

/** Every path passed to api.get in services/api.ts, with ${...} placeholders
 *  normalised to ':param' so it can be matched against the lists. */
function uiGetPaths(source: string): string[] {
  const calls = source.matchAll(/api\.get(?:<[^(]*?>)?\(\s*(['`])(.+?)\1/g)
  const paths = [...calls].map((m) => m[2].split('?')[0].replace(/\$\{[^}]+\}/g, ':param'))
  return [...new Set(paths)].sort()
}

const concrete = (path: string) => `/api/v1${path.replace(/:param/g, 'x1')}`
const isServed = (path: string) => {
  const res = sampleResponse(concrete(path), {})
  return !(res && typeof res === 'object' && !Array.isArray(res) && Object.keys(res).length === 0)
}

describe('demo mode covers every GET the UI makes', () => {
  const paths = uiGetPaths(apiSource)

  it('finds the GET calls in services/api.ts', () => {
    // A sanity floor so a refactor of api.ts can't make this test vacuous.
    expect(paths.length).toBeGreaterThan(20)
    expect(paths).toContain('/budgets')
  })

  it.each(paths)('%s is served by the sample account or listed with a reason', (path) => {
    const listed = path in UNSAMPLED_BY_DESIGN || path in KNOWN_DEMO_GAPS
    expect(isServed(path) || listed, `${path} returns {} in demo mode; add it to sampleResponse or list it`).toBe(true)
  })

  it.each(Object.keys({ ...UNSAMPLED_BY_DESIGN, ...KNOWN_DEMO_GAPS }))(
    '%s is still an unserved GET (drop it from the list once it is served or removed)',
    (path) => {
      expect(paths).toContain(path)
      expect(isServed(path)).toBe(false)
    },
  )

  it('a path is never both by design and a known gap', () => {
    const both = Object.keys(UNSAMPLED_BY_DESIGN).filter((p) => p in KNOWN_DEMO_GAPS)
    expect(both).toEqual([])
  })
})
