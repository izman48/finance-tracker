/** Anonymize numbers: while active, the app shows a fixed, self-contained
 *  SAMPLE account — fake banks, merchants and figures with no relation to your
 *  real data — instead of your own. Your real data is simply not fetched while
 *  it's on, and writes are blocked. It is a privacy convenience for screenshots
 *  and showing the app, NOT a security feature.
 *
 *  The sample dataset lives in lib/sampleAccount.ts; the axios interceptor
 *  (services/api.ts) serves it in place of the real API while active. This file
 *  is just the on/off store.
 */

const ON_KEY = 'anon.on'

function ss(): Storage | null {
  try {
    return typeof sessionStorage !== 'undefined' ? sessionStorage : null
  } catch {
    return null
  }
}

let on = ss()?.getItem(ON_KEY) === '1'
const listeners = new Set<() => void>()

export const isAnonymized = () => on

export function setAnonymized(next: boolean) {
  const store = ss()
  if (next) store?.setItem(ON_KEY, '1')
  else store?.removeItem(ON_KEY)
  on = next
  // Reload so every page re-fetches through the interceptor with the new state,
  // flipping the whole app between real and sample data at once.
  if (typeof window !== 'undefined') window.location.reload()
  listeners.forEach((l) => l())
}

export function subscribeAnonymized(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}
