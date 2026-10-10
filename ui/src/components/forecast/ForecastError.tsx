import { forwardRef } from 'react'

/** The sprint 07 sentence, verbatim (ux spec nilu-s08-claude-changes.md section 4). */
export const FORECAST_ERROR_TEXT = "Couldn't load your forecast. Try another range or refresh the page."

type Props = { retrying: boolean; onRetry: () => void }

/**
 * Shown when the forecast request fails or times out. It deliberately takes
 * no message: server or axios text must never reach the screen.
 */
const ForecastError = forwardRef<HTMLButtonElement, Props>(function ForecastError({ retrying, onRetry }, ref) {
  return (
    <div className="h-64 flex flex-col items-center justify-center gap-3 text-center">
      <p role="alert" className="text-sm text-slate-300 max-w-xs">
        {FORECAST_ERROR_TEXT}
      </p>
      <button ref={ref} type="button" className="btn-ghost" onClick={onRetry} disabled={retrying} aria-busy={retrying}>
        {retrying ? 'Trying…' : 'Try again'}
      </button>
    </div>
  )
})

export default ForecastError
