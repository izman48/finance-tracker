import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ForecastError, { FORECAST_ERROR_TEXT } from './ForecastError'

// The suite runs in node (no DOM library), so read the static markup.
const text = (html: string) => html.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'")

describe('ForecastError (F1, F3)', () => {
  it('F1: shows the sprint 07 sentence verbatim as an alert, with Try again', () => {
    expect(FORECAST_ERROR_TEXT).toBe("Couldn't load your forecast. Try another range or refresh the page.")
    const html = renderToStaticMarkup(<ForecastError retrying={false} onRetry={() => {}} />)
    expect(html).toContain('role="alert"')
    expect(text(html)).toContain(FORECAST_ERROR_TEXT)
    expect(text(html)).toContain('Try again')
    expect(text(html)).not.toContain('Loading forecast')
    expect(html).toContain('h-64')
    expect(html).toContain('btn-ghost')
  })

  it('F1: takes no message, so server or axios text can never be shown', () => {
    // The component's props are only the retry state and handler.
    const html = renderToStaticMarkup(<ForecastError retrying={false} onRetry={() => {}} />)
    expect(text(html)).toBe(FORECAST_ERROR_TEXT + 'Try again')
  })

  it('F3: while retrying the button reads Trying…, disabled and busy', () => {
    const html = renderToStaticMarkup(<ForecastError retrying onRetry={() => {}} />)
    expect(text(html)).toContain('Trying…')
    expect(html).toMatch(/<button[^>]*disabled/)
    expect(html).toContain('aria-busy="true"')
  })

  it('uses no low-contrast slate shades (text-slate-400 or lighter)', () => {
    const html = renderToStaticMarkup(<ForecastError retrying={false} onRetry={() => {}} />)
    expect(html).not.toMatch(/text-slate-(500|600|700)/)
  })

  it('ux: the Try again button is at least 44px tall', () => {
    const html = renderToStaticMarkup(<ForecastError retrying={false} onRetry={() => {}} />)
    expect(html).toMatch(/<button[^>]*class="[^"]*min-h-\[44px\]/)
  })
})

describe('ForecastChart heading (F3 focus target)', () => {
  it('is focusable by script and shows the app focus ring, not the browser outline', async () => {
    const { default: ForecastChart } = await import('../ForecastChart')
    const html = renderToStaticMarkup(<ForecastChart />)
    const h2 = html.match(/<h2[^>]*>/)?.[0] ?? ''
    expect(h2).toContain('tabindex="-1"')
    expect(h2).toContain('focus:outline-none')
    expect(h2).toContain('focus-visible:outline-accent/60')
  })
})
