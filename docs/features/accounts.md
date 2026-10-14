# Accounts, roles and card repayments

Lists connected accounts with balances and freshness. The user sets each
account's cashflow role (spending, savings, credit, excluded), overdraft and,
for credit cards, how the balance is repaid. Money owed on cards is shown
with one sign whatever the provider. Each card can hold its statements
(balance, statement date, due date, optional minimum), from which the API
derives the amount still due and the spend since the statement (unbilled).

## Code

**API**:

| Route | Auth |
|---|---|
| `GET /api/v1/banking/accounts` | `CurrentUserOrMcpRead`; adds `credit_owed`, `last_synced_at`, `sync_stale`. |
| `PATCH /api/v1/analytics/accounts/{account_id}/settings` | `CurrentUser`; role, overdraft, repayment config, `pay_from_account_id`. |
| `GET /api/v1/analytics/accounts/{account_id}/repayments` | `CurrentUser` |
| `POST /api/v1/analytics/accounts/{account_id}/repayments` | `CurrentUser` |
| `DELETE /api/v1/analytics/accounts/{account_id}/repayments/{item_id}` | `CurrentUser` |
| `GET /api/v1/analytics/accounts/{account_id}/statements` | `CurrentUser`; newest 24 statements plus `current` (amount still due, unbilled, paid), derived on read. |
| `POST /api/v1/analytics/accounts/{account_id}/statements` | `CurrentUser`; manual statement, credit accounts only (else 422); same card and date twice is 409. |
| `PATCH /api/v1/analytics/accounts/{account_id}/statements/{statement_id}` | `CurrentUser` |
| `DELETE /api/v1/analytics/accounts/{account_id}/statements/{statement_id}` | `CurrentUser`; the card goes back to its current balance. |

**Tables**: `accounts` (encrypted names and balances; plaintext
`external_id`, `account_type`, `currency`), `account_settings` (kept apart
from `accounts` so sync never overwrites them), `repayment_schedule_items`
(encrypted `amount`), `card_statements` (encrypted `statement_balance`,
`minimum_due`; plaintext dates and `source` = `manual` or `provider`; unique
per card, statement date and source).

**Services**: `services/balance_sign.py` (`credit_owed`: the only way to read
money owed; unverified providers fall back to `abs()`),
`services/analytics/common.py` (`default_role`, `resolve_roles`),
`services/analytics/repayments.py` (strategies `full_balance`, `fixed`,
`installments`, `minimum_percent`, `scheduled`; a card repayment and its
linked commitment count once), `services/analytics/card_links.py`,
`services/analytics/statements.py` (current statement, amount still due,
unbilled; only credits identified as payments reduce the amount due, so a
refund leaves the full statement due: fail-safe). Statements don't change any
figure yet: no repayment strategy reads them (T-10-3 adds one).

**UI**: `AccountSettingsModal` (opened from Wealth), `lib/credit.ts`; account
filter on Spending.

**MCP**: `accounts`.

**Tests**: `api/tests/integration/test_accounts_credit_owed.py`,
`test_account_ownership.py`; `api/tests/unit/test_credit_sign.py`,
`test_card_link.py`, `test_card_installments.py`,
`test_card_repayment_once.py`, `test_card_payment_indicators.py`,
`test_card_statement_position.py`; `api/tests/integration/test_card_statements_api.py`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `accounts`, `account_settings`, `repayment_schedule_items`, `card_statements`. |
| 2 Purge | Yes, all four. |
| 3 Deletion | Cascade via `bank_connections` → `accounts`; `card_statements` also cascades from `users` (tested with SQLite foreign keys on). |
| 4 Demo mode | `/banking/accounts` served (no balances). **Gap**: repayments are in `KNOWN_DEMO_GAPS`. Statements have no UI caller yet; the card settings UI (T-10-6) adds them to the sample account. |
| 5 Ownership | Yes, every route here (`owned_account`, `require_owned_account_ids`). |
| 6 Scopes | Accounts list `finance:read`; settings, repayments and statements web only. |
| 7 Claude tools | `accounts` (read only). |
| 8 Audit | Not audited (web-only writes). |
| 9 Bank sync | Sync updates names, type, balances; settings and statements untouched. Amount still due and unbilled are computed on read from the card's balance and transactions. |
| 10 Home | Cash and credit owed on the Cashflow and Wealth cards. Owned by Wealth. |
| 11 UI routes | Modal on `/networth`. |
| 12 Tests | listed above. |
| 13 Docs | `CLAUDE.md` gotcha "Credit-card sign". |
