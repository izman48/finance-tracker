# Bank sync and freshness

Pulls fresh balances and transactions from every connected bank: at login, on
resume when data is stale, when the user asks, or through Claude's
`refresh_banks` tool. There are no background jobs: sync needs the user's
data key, which only exists inside a request.

## Code

**API** (`api/app/routers/banking.py`):

| Route | Auth | Notes |
|---|---|---|
| `POST /api/v1/banking/sync/accounts` | `CurrentUser` | Web sync of accounts and balances; DB lease, sends X-PSU-IP. |
| `POST /api/v1/banking/sync/transactions` | `CurrentUser` | Body `{days}`; non-history syncs are clamped to 88 days. |
| `POST /api/v1/banking/sync` | web or `finance:sync` | Claude's sync: one at a time, 10-minute cooldown (`SYNC_COOLDOWN_SECONDS`), 45 s budget, per-connection result only, never error text. |
| `GET /api/v1/banking/sync-status` | `CurrentUserOrMcpRead` | Stored freshness only; stale after 48 h. |

**Tables**: `user_sync_locks` (lease and cooldown, no user data). Writes
`accounts`, `transactions`, `bank_connections.last_synced_at`, `card_statements` (provider rows).

**Services**: `services/truelayer.py` (`sync_accounts`, `sync_transactions`;
per-account isolation, 403 → 88-day fallback, Revolut/Amex card fallbacks,
balance fail-safe; on a credit card it also keeps the provider statement
from the same balance response, `services/provider_statements.py`, logging
field-presence booleans per provider id only, plus `statement_owes` (after the sign rule) and
`stored`; that line has its own INFO handler so it shows in production, where `app.*` INFO
logs otherwise don't), `services/sync_lock.py`, `services/sync_status.py`,
`core/rate_limit.py` (`user_in_flight`).

**What runs on new transactions**: `categorization.apply_rules`. Everything
else (commitments, forecast, spending, budgets) is computed on the next read.

**UI**: `hooks/useAuth.tsx` (365 days after login and on stale resume),
`NetWorthPage` (1825 days), `DashboardPage` (90 days), `BudgetsPanel` (reads
sync-status for its freshness line).

**MCP**: `sync_status`, `refresh_banks`.

**Tests**: `api/tests/integration/test_bank_sync_api.py`,
`test_sync_lock.py`, `test_sync_budget.py` (the 45 s time budget, not
budgets), `test_sync_per_account.py`, `test_sync_revolut_amex.py`,
`test_sync_window.py`, `test_sync_status.py`, `test_psu_ip_header.py`;
`api/mcp/tests/test_bank_sync_tool.py`, `test_sync_status.py`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `user_sync_locks`. |
| 2 Purge | Not purged; holds no user data. |
| 3 Deletion | Cascades from `users`. |
| 4 Demo mode | **Gap**: `/banking/sync-status` is in `KNOWN_DEMO_GAPS`. Sync POSTs are blocked. |
| 5 Ownership | n/a. |
| 6 Scopes | `finance:sync` opens only `POST /api/v1/banking/sync`; `finance:read` for sync-status. |
| 7 Claude tools | `sync_status`, `refresh_banks`. |
| 8 Audit | Not audited (no user data changes). |
| 9 Bank sync | This feature. |
| 10 Home | Header syncing strip. |
| 11 UI routes | none of its own. |
| 12 Tests | listed above. |
| 13 Docs | `CLAUDE.md` "Remote MCP / OAuth". |
