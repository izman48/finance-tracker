import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  FORECAST_TIMEOUT_MS,
  focusAfter,
  forecastReducer,
  withTimeout,
  type ForecastView,
} from './forecastLoad'

// T-08-13, ux spec nilu-s08-claude-changes.md section 4 (F1-F4).

const loading: ForecastView<number> = { status: 'loading' }
const error: ForecastView<number> = { status: 'error', retrying: false }
const retrying: ForecastView<number> = { status: 'error', retrying: true }
const ready: ForecastView<number> = { status: 'ready', data: 1 }

describe('withTimeout (F2)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('rejects a request that never answers after 10 s', async () => {
    vi.useFakeTimers()
    const never = new Promise<number>(() => {})
    const settled = vi.fn()
    withTimeout(never, FORECAST_TIMEOUT_MS).then(settled, (e) => settled(e))
    await vi.advanceTimersByTimeAsync(FORECAST_TIMEOUT_MS - 1)
    expect(settled).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(settled).toHaveBeenCalledOnce()
    expect(settled.mock.calls[0][0]).toBeInstanceOf(Error)
    expect(FORECAST_TIMEOUT_MS).toBe(10_000)
  })

  it('passes a timely answer through and clears its timer', async () => {
    vi.useFakeTimers()
    await expect(withTimeout(Promise.resolve(7), FORECAST_TIMEOUT_MS)).resolves.toBe(7)
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('forecastReducer', () => {
  it('F1: a failure is an error view that carries no message', () => {
    const next = forecastReducer(loading, { type: 'failed' })
    expect(next).toEqual({ status: 'error', retrying: false })
  })

  it('F3: retry keeps the error view, marked as trying', () => {
    expect(forecastReducer(error, { type: 'retry' })).toEqual(retrying)
    // The fetch that the retry triggers does not swap in the loading view.
    expect(forecastReducer(retrying, { type: 'start' })).toEqual(retrying)
  })

  it('F3: a retry that fails returns to the plain error view', () => {
    expect(forecastReducer(retrying, { type: 'failed' })).toEqual(error)
  })

  it('F3: a retry that succeeds replaces the error with the chart', () => {
    expect(forecastReducer(retrying, { type: 'loaded', data: 1 })).toEqual(ready)
  })

  it('F4: choosing another range from the error view loads again', () => {
    expect(forecastReducer(error, { type: 'start' })).toEqual(loading)
  })

  it('never keeps stale numbers once a request fails', () => {
    expect(forecastReducer(ready, { type: 'start' })).toEqual(loading)
    expect(forecastReducer(loading, { type: 'failed' })).not.toHaveProperty('data')
  })
})

describe('focusAfter (F3)', () => {
  it('moves focus to the card heading when a retry succeeds', () => {
    expect(focusAfter(retrying, ready)).toBe('heading')
  })
  it('keeps focus on Try again when a retry fails', () => {
    expect(focusAfter(retrying, error)).toBe('retry')
  })
  it('leaves focus alone otherwise', () => {
    expect(focusAfter(loading, ready)).toBeNull()
    expect(focusAfter(loading, error)).toBeNull()
    expect(focusAfter(error, retrying)).toBeNull()
  })
})
