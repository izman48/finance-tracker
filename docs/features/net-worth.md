# Net worth and assets (Wealth tab)

The balance sheet: bank accounts plus manually tracked assets and
liabilities (ISA, savings, investment, pension, property, crypto, mortgage,
loan…), with dated valuations and recorded contributions, less the loans,
finance and BNPL in [liabilities.md](liabilities.md). Shows net worth
today and its change, month-end history, contributions versus growth, and a
compound projection with every assumption echoed back.

## Code

**API**:

| Route | Auth |
|---|---|
| `GET /api/v1/analytics/net-worth-history` | `CurrentUser` (`months` 1–60) |
| `GET /api/v1/analytics/net-worth-position` | `CurrentUser` |
| `GET /api/v1/analytics/net-worth-decomposition` | `CurrentUser` |
| `GET /api/v1/analytics/net-worth-projection` | `CurrentUser` (`spending_source` = budgets / average / none, T-10-15b) |
| `GET /api/v1/assets` | `CurrentUser` |
| `POST /api/v1/assets` | `CurrentUser` |
| `PATCH /api/v1/assets/{asset_id}` | `CurrentUser` (growth %, monthly contribution) |
| `DELETE /api/v1/assets/{asset_id}` | `CurrentUser` |
| `POST /api/v1/assets/{asset_id}/valuations` | `CurrentUser` (same date overwrites) |
| `DELETE /api/v1/assets/{asset_id}/valuations/{valuation_id}` | `CurrentUser` |
| `POST /api/v1/assets/{asset_id}/flows` | `CurrentUser` |
| `DELETE /api/v1/assets/{asset_id}/flows/{flow_id}` | `CurrentUser` |

**Tables**: `assets` (encrypted `name`, `monthly_contribution`; plaintext
`assumed_growth_pct`), `asset_valuations` (encrypted `value`; liabilities are
negative), `asset_flows` (encrypted `amount`). Instrument pricing was added
and then dropped by migration; `REDESIGN_PLAN.md` still describes it.

**Net worth and liabilities (T-10-7b)**: every surface takes liabilities
from one function, `net_worth.liabilities_total`: the summary
(`liabilities_total`, `net_worth`, and `total_owed` = cards owed +
liabilities from `net_worth.total_owed`, T-10-14a; Claude reads it through
`cashflow_summary`), and the series behind position, history and projection
(`liabilities` on each point). In the history a liability counts at today's
balance from the earlier of its start date and its as-of date, so adding a
loan that started earlier shifts the whole series instead of showing a drop
that month. The projection carries it as its own `liabilities` component
(`assets` stays the manual assets). A linked liability follows its schedule
(its repayment is in the cashflow as the commitment); an unlinked one stays
flat, since nothing says a payment leaves the bank (overstates debt). The decomposition is
manual-asset movement only, so a liability doesn't change it. A `loan` or
`other_liability` asset is replaced only through the id the user picked
(`replaces_asset_id` on `POST /api/v1/liabilities`, one transaction, the
asset row locked). Until then both count, which overstates debt and never
drops it silently. The "both counted" notice is UI (T-10-10).

**Holding kinds (ADR-002, T-11-3a)**: `services/holdings/registry.py` has
one entry per stored `asset_type` and liability `kind`: its group
(investments, savings, property, other, debt), projection model (growth,
amortisation, flat), whether it is debt or an investment, the commitment
link it can carry, and how it reaches every surface (net worth, projection,
commitments, Cashflow, Claude, demo, purge, docs). `INVESTMENT_KINDS` (isa,
investment, pension, crypto; owner D1) is the one list behind "Include
investments" and `investments_total`. A stored type with no entry is the
`unknown` kind of its table, held flat and never hidden: an unknown asset
counts at its stored value and sign, an unknown liability counts as debt. Adding a
kind is a registry entry plus tests; `tests/unit/test_holding_registry.py`
fails if it skips a surface, and `check_feature_docs.py` checks its docs
file exists. Design: `docs/engineering/adr-002-holdings-and-flows.md`.

**Projection spending (T-10-15b)**: `spending_source` picks the monthly
spending the projection subtracts: the total of active, unpaused budget
limits (`budgets`, the same `cycle_budgets` figure as the Cashflow budget
line), the measured average or the user's estimate (`average`), or nothing
(`none`). Budgets with a £0 total fall back to the average
(`budgets_fallback`), never to £0 spending. Sent, it wins over the old
`subtract_spending`; `monthly_spending` applies only to `average`; omitted,
the result is today's. The basis echoes `spending_choice`, `spending_used`,
`budgets_monthly` and the figure applied, so the UI's evidence line prints
the API's numbers. Nothing is stored server-side. UI: the "Everyday
spending" radio group (`components/wealth/SpendingChoice.tsx`,
`lib/projectionSpending.ts`) in the target form's cashflow mode: My budgets
(the default, disabled with "Add a budget to use this." when there are none),
Average past spending (with the optional estimate) and None. The choice is
kept in `wealth.spendingSource`; the old `wealth.subtractSpending = '0'` maps
to None and a stored `wealth.monthlySpend` to Average. The budgets line says
"a pay cycle" unless the budget cycle is a calendar month (budgets are per
cycle).

**Holdings engine (ADR-002, T-11-4)**: every asset's value today and
forecast come from the holding engine (`api/app/services/holdings/`);
`include_investments=true|false` on history and projection drops the
investment kinds only. Growth % is bounded −100..50 and values ±10,000,000.

**Services**: `services/analytics/net_worth.py` (history, position,
`assets_total`, `liabilities_total`, `asset_decomposition`), `services/analytics/projections.py`
(surplus from the cashflow engine, honours Claude holds).

**UI**: `/networth` (`NetWorthPage`; the balance sheet's groups, in order,
are in `lib/balanceSheet.ts`: "Current accounts", "Savings", …, "Credit
cards", "Loans and finance", each a `section` labelled by its heading
(T-10-14c). "Credit cards" holds credit-role bank accounts only; a manual
asset worth less than nothing sits in "Loans and finance" (`assetGroup`). Card rows (`components/wealth/CardRow.tsx`) show the statement
from the summary's `statement` via `lib/cardStatement.ts`, shared with
Cashflow; "Add statement" / "Add new" open card settings. "Loans and finance"
lists liabilities, see [liabilities.md](liabilities.md)), `PositionStrip` (its breakdown line
subtracts what is owed on liabilities), `AddAssetModal`,
`UpdateAssetValueModal`, `AddToBalanceSheetChooser`, `lib/assets.ts`. Home
Wealth card.

**Tests**: `api/tests/integration/test_net_worth_liabilities.py` (every
surface, conversion), `test_projection_budgets.py` (T-10-15b), `api/tests/unit/test_net_worth.py`,
`test_projection_counts_once.py`, `test_holding_registry.py`; `api/tests/integration/test_api.py`,
`test_budget_invariance.py`, `test_reset_purge.py`; UI
`sampleAccount.test.ts` (sample balance sheet).

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `assets`, `asset_valuations`, `asset_flows`. |
| 2 Purge | Yes, all three. |
| 3 Deletion | Cascade from `users` and `assets`. |
| 4 Demo mode | All four net-worth reads and `/assets` served. |
| 5 Ownership | n/a (no account ids). |
| 6 Scopes | Web only (`test_oauth.py` checks). |
| 7 Claude tools | none; net worth (with liabilities subtracted) reaches Claude only inside `cashflow_summary`. |
| 8 Audit | Web-only writes, not audited. |
| 9 Bank sync | History is rebuilt on read from synced transactions. |
| 10 Home | Wealth card (net worth and changes, sparkline, Total owed from `total_owed`). Owned by Wealth. |
| 11 UI routes | `/networth`. |
| 12 Tests | listed above; no route tests for valuations or flows, no UI tests. |
| 13 Docs | this file. |
