# Spending insight (Spending tab)

Where money went, by category and merchant, under two lenses: `money_out`
(reconciles with bank statements, with a composition of card repayments,
transfers, commitments and other) and `purchases`. Periods: since payday,
this month, last 30 days, custom. Drill into the transactions behind any
figure, and see a monthly trend over 1 to 24 months. Budgets live on this
tab too ([budgets.md](budgets.md)).

## Code

**API** (`api/app/routers/analytics.py`):

| Route | Auth |
|---|---|
| `GET /api/v1/analytics/spending` | `CurrentUserOrMcpRead` |
| `GET /api/v1/analytics/spending/trend` | `CurrentUserOrMcpRead` |
| `GET /api/v1/analytics/spending/transactions` | `CurrentUser` (unused by UI and MCP; the UI drills down with `/banking/transactions?kind=`) |

**Tables**: none of its own. Reads `transactions`, `accounts`,
`account_settings`, `commitment_rules`, `planned_items`.

**Services**: `services/analytics/spending.py` (`classify_noise`,
`classify_purchase`, transfer and card-settlement detection,
`financed_transaction_ids`), `services/analytics/common.py`.

**UI**: `/insights` (`SpendingPage`), `MonthlySpendingChart`,
`lib/categoryColors.ts`. Home Spending card. The account filter lists
accounts in `<optgroup>`s, Current accounts, Savings, Credit cards (roles from
the summary, as Wealth and Cashflow; excluded accounts left out;
`lib/accountOptions.ts`, T-10-16). Excluded accounts can't be picked in the
filter.

**MCP**: `spending`, `spending_trend`.

**Tests**: `api/tests/unit/test_analytics_service.py`,
`test_transfer_category.py`, `test_counts_as.py`,
`test_card_payment_indicators.py`; `api/tests/integration/test_budget_spend.py`,
`test_transactions_endpoint.py`; UI `sampleAccount.test.ts`
(the sample's spending reconciles).

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | none. |
| 2 Purge | Inputs purged. |
| 3 Deletion | Inputs cascade. |
| 4 Demo mode | Served; `sampleAccount.test.ts` checks headline = sum of parts. |
| 5 Ownership | `account_id` is a read filter over the user's own data. |
| 6 Scopes | `finance:read` except `/spending/transactions`. |
| 7 Claude tools | `spending`, `spending_trend`. |
| 8 Audit | n/a. |
| 9 Bank sync | Computed on read. |
| 10 Home | Spending card (month to date vs last month, sparkline, top categories, budget line). Owned by Spending. |
| 11 UI routes | `/insights`. |
| 12 Tests | listed above. |
| 13 Docs | this file. |
