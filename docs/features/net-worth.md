# Net worth and assets (Wealth tab)

The balance sheet: bank accounts plus manually tracked assets and
liabilities (ISA, savings, investment, pension, property, crypto, mortgage,
loan…), with dated valuations and recorded contributions. Shows net worth
today and its change, month-end history, contributions versus growth, and a
compound projection with every assumption echoed back.

## Code

**API**:

| Route | Auth |
|---|---|
| `GET /api/v1/analytics/net-worth-history` | `CurrentUser` (`months` 1–60) |
| `GET /api/v1/analytics/net-worth-position` | `CurrentUser` |
| `GET /api/v1/analytics/net-worth-decomposition` | `CurrentUser` |
| `GET /api/v1/analytics/net-worth-projection` | `CurrentUser` |
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

**Services**: `services/analytics/net_worth.py` (history, position,
`assets_total`, `asset_decomposition`), `services/analytics/projections.py`
(surplus from the cashflow engine, honours Claude holds).

**UI**: `/networth` (`NetWorthPage`), `PositionStrip`, `AddAssetModal`,
`UpdateAssetValueModal`, `AddToBalanceSheetChooser`, `lib/assets.ts`. Home
Wealth card.

**Tests**: `api/tests/unit/test_net_worth.py`,
`test_projection_counts_once.py`; `api/tests/integration/test_api.py`,
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
| 7 Claude tools | none; net worth reaches Claude only inside `cashflow_summary`. |
| 8 Audit | Web-only writes, not audited. |
| 9 Bank sync | History is rebuilt on read from synced transactions. |
| 10 Home | Wealth card (net worth and changes, sparkline, credit owed). Owned by Wealth. |
| 11 UI routes | `/networth`. |
| 12 Tests | listed above; no route tests for valuations or flows, no UI tests. |
| 13 Docs | this file. |
