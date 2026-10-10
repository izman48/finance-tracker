/**
 * Loading states for the Cashflow forecast card (T-08-13). Kept free of React
 * and the DOM so the error, retry and timeout rules are unit-tested.
 *
 * An error view never carries the server's or axios's message: the card only
 * ever shows the spec's own sentence.
 */

/** A request that hasn't answered by then is shown as an error, never as endless loading. */
export const FORECAST_TIMEOUT_MS = 10_000

export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timed out')), ms)
    promise.then(
      (value) => {
        clearTimeout(timer)
        resolve(value)
      },
      (err) => {
        clearTimeout(timer)
        reject(err)
      },
    )
  })
}

export type ForecastView<T> =
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; retrying: boolean }

export type ForecastAction<T> =
  | { type: 'start' } // a request is going out (range change, refresh or retry)
  | { type: 'retry' } // the user pressed Try again
  | { type: 'loaded'; data: T }
  | { type: 'failed' }

export function forecastReducer<T>(view: ForecastView<T>, action: ForecastAction<T>): ForecastView<T> {
  switch (action.type) {
    case 'start':
      // A retry stays on the error view (the button shows "Trying…");
      // anything else shows loading, never the previous numbers.
      return view.status === 'error' && view.retrying ? view : { status: 'loading' }
    case 'retry':
      return { status: 'error', retrying: true }
    case 'loaded':
      return { status: 'ready', data: action.data }
    case 'failed':
      return { status: 'error', retrying: false }
  }
}

/** Where focus goes after a retry settles: the card heading on success, back to Try again on failure. */
export function focusAfter<T>(prev: ForecastView<T>, next: ForecastView<T>): 'heading' | 'retry' | null {
  if (prev.status !== 'error' || !prev.retrying) return null
  if (next.status === 'ready') return 'heading'
  if (next.status === 'error' && !next.retrying) return 'retry'
  return null
}
