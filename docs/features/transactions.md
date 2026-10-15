# Transactions

A filterable, paginated list that reconciles with the spending figures,
dropdown facets, an exact merchant/description search for Claude, and
per-transaction edits (category, sub-category, "counts as").

## Code

**API** (`api/app/routers/banking.py`):

| Route | Auth | Notes |
|---|---|---|
| `GET /api/v1/banking/transactions` | `CurrentUserOrMcpRead` | Filters run in Python (encrypted columns). Adds computed `excluded_reason`, `is_commitment`, `is_financed`. `kind` = spend, cash, credit, money_out. |
| `POST /api/v1/banking/transactions/search` | `CurrentUserOrMcpRead` | 10/min per user, one at a time, capped window. |
| `GET /api/v1/banking/transactions/facets` | `CurrentUser` | |
| `PATCH /api/v1/banking/transactions/{transaction_id}` | `CurrentUser` | `category` learns a rule (`learn_and_apply`); null or "" clears it and forgets the rule (T-12-12); category/subcategory up to 100 visible characters (422); `counts_as` sets a locked override. |

**Tables**: `transactions` (encrypted `amount`, `description`,
`merchant_name`; plaintext `category`, `subcategory`, locks, dates). A
migration backup table `category_backfill_t08_1` exists (not ORM-mapped).

**Services**: `services/transaction_search.py`,
`services/categorization.py`, `services/analytics/spending.py`
(`classify_noise`, `financed_transaction_ids`).

**UI**: `SpendingPage` (list, CSV export, bulk category, facets),
`TransactionDetailSheet` (edits, mark recurring, pay on finance). `/transactions` redirects
to `/insights`.

**MCP**: `recent_transactions`, `search_transactions`.

**Tests**: `api/tests/integration/test_transactions_endpoint.py`,
`test_transaction_search.py`, `test_transaction_search_cost.py`,
`test_provider_category_endpoints.py`;
`api/tests/unit/test_transaction_search_window.py`, `test_counts_as.py`,
`test_transfer_category.py`; `api/mcp/tests/test_search_transactions.py`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `transactions`. |
| 2 Purge | Yes. |
| 3 Deletion | Cascade via `accounts`. |
| 4 Demo mode | List and facets served from the one sample ledger; edits blocked. |
| 5 Ownership | List `account_id` is AND-ed with the user's accounts (read). PATCH joins `Account` on user. |
| 6 Scopes | List and search `finance:read`; facets and edits web only. |
| 7 Claude tools | `recent_transactions`, `search_transactions`. |
| 8 Audit | Edits are web only, not audited. |
| 9 Bank sync | New rows get `category_from_provider`, then `apply_rules`. |
| 10 Home | n/a (drill-down from Spending). |
| 11 UI routes | `/insights`, `/transactions` (redirect). |
| 12 Tests | listed above. |
| 13 Docs | this file. |
