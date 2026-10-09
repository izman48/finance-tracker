import { gbp, gbp0, dateDayMonth as shortDate } from '../lib/format'

/** One spending account's first breach (API: ForecastResponse.account_breaches). */
export interface AccountBreach {
  account_id: string | null
  account_name: string | null
  date: string
  balance: number | string // Decimal, arrives as a string
  floor: number | string   // -|limit|, or 0 when no limit is recorded
  kind: string             // overdraft | zero
}

/** The fields of the forecast the headline block reads. */
export interface ForecastHeadline {
  min_balance: number
  min_date: string
  overdraft_limit: number
  breaches: string[]
  account_breaches: AccountBreach[]
  unassigned_attributed_to: string | null
}

export const OVERDRAFT_LINE_LABEL = 'total overdraft limit'

/** Suffix for the pooled lowest point, from the pooled numbers only:
 * `breaches` also holds per-account kinds, so it can't speak for the pool. */
function pooledSuffix(minBalance: number, limit: number): string {
  if (minBalance >= 0) return ''
  if (limit > 0 && minBalance < -limit) return ' — exceeds your total overdraft limit'
  return limit > 0 ? ' — dips into overdraft' : ' — goes below £0'
}

/** One line per account. "Overdraft" never describes an account with no limit. */
function breachLine(b: AccountBreach): string {
  const name = b.account_name ?? 'Items with no account'
  const floor = Number(b.floor)
  const when = shortDate(b.date)
  const bal = gbp(Number(b.balance))
  if (floor === 0) {
    return `${name} goes below £0 on ${when} (down to ${bal}). It has no overdraft limit set.`
  }
  const limit = gbp0(Math.abs(floor))
  if (b.kind === 'overdraft') {
    return `${name} goes past its ${limit} overdraft limit on ${when} (down to ${bal}).`
  }
  return `${name} dips into its overdraft on ${when} (down to ${bal}), within its ${limit} limit.`
}

export default function ForecastSummary({ data }: { data: ForecastHeadline }) {
  const breached = data.breaches.length > 0
  const suffix = pooledSuffix(data.min_balance, data.overdraft_limit)
  const accounts = data.account_breaches ?? []
  // Only the account the forecast put unassigned items on can be uncertain.
  const estimated = accounts.find(
    (b) => data.unassigned_attributed_to != null && b.account_id === data.unassigned_attributed_to,
  )

  return (
    <div className="mb-3 text-sm">
      <p className={breached ? 'text-neg' : 'text-slate-400'} data-testid="forecast-headline">
        {breached && <span aria-hidden="true">⚠ </span>}
        <span>Lowest point: </span>
        <span className="font-semibold tnum">{gbp0(data.min_balance)}</span>
        <span> on {shortDate(data.min_date)}{suffix}</span>
      </p>
      {accounts.length > 0 && !suffix && (
        <p className="text-slate-400">
          Your accounts together stay above £0, but{' '}
          {accounts.length === 1 ? 'one account does not.' : `${accounts.length} accounts do not.`}
        </p>
      )}
      {accounts.length > 0 && (
        <ul className="text-neg">
          {accounts.map((b) => (
            <li key={b.account_id ?? 'unassigned'}>
              {breachLine(b)}
              {b === estimated ? ' *' : ''}
            </li>
          ))}
        </ul>
      )}
      {estimated && (
        <p className="text-slate-400">
          * Estimated: items with no account set are counted against {estimated.account_name}, your
          highest-balance spending account. Set an account on them to make this exact.
        </p>
      )}
    </div>
  )
}
