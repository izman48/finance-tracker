# Per-user encryption, key-loss purge and account deletion

The rules every table has to follow. Read this before adding a table.

## Per-user encryption

- Transaction text and amounts, account details, bank tokens and most derived
  data are encrypted with a per-user data key (DEK). The server holds the DEK
  only during a request: it is wrapped at rest under the password and the
  recovery code (Argon2id), and travels in the JWT `dk` claim encrypted with
  the server key.
- Column types (`core/encryption.py`): `UserEncryptedString`,
  `UserEncryptedDecimal`, `UserEncryptedToken` (DEK inside, server key
  outside). All fail closed with `DEKUnavailableError` → 401.
- Consequences: no SQL filtering or aggregation on encrypted columns (compute
  in Python); no background jobs can read bank data; always scope queries by
  user.

## Key-loss purge

`POST /api/v1/auth/reset-password` without a recovery code calls
`purge_data_under_lost_key` (`api/app/services/key_loss_purge.py`), in one
transaction:

1. By `user_id`: `write_idempotency`, `budget_nudges`,
   `budget_cycle_snapshots`, `budget_changes`, `budgets`, `audit_entries`,
   `category_rules`, `rule_packs`, `liabilities`, `commitment_rules`, `planned_items`,
   `repayment_schedule_items`, `card_statements`, `account_settings`.
2. `asset_valuations`, `asset_flows`, then `assets`.
3. `transactions`, `accounts`, then `bank_connections`.
4. `oauth_grants` are revoked (not deleted); `oauth_authorization_codes` are
   deleted.

Kept: `users`, `user_sync_locks` (no user data), `oauth_clients` (not
per-user).

`api/tests/integration/test_reset_purge.py` finds every table with a
`UserEncrypted*` column from SQLAlchemy metadata and fails until the purge
deletes it. Plaintext-only tables (like `budget_nudges`) are not caught by
that guard; add them to the purge by hand.

## Account deletion

`POST /api/v1/auth/delete-account` deletes `bank_connections`, then the
`users` row, and relies on `ON DELETE CASCADE` from `users.id` for every other
table (`transactions` cascade through `accounts`; asset children through
`assets`). A new user-owned table must declare that cascade in both the model
and the migration.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | Owns no tables; defines the rules above for all of them. |
| 2 Purge | This feature. |
| 3 Deletion | This feature. Not covered by a test (gap). |
| 4 Demo mode | n/a. |
| 5 Ownership | n/a. |
| 6 Scopes | Web only. |
| 7 Claude tools | none. A purge revokes Claude's grants. |
| 8 Audit | `audit_entries` are purged. |
| 9 Bank sync | Sync needs the DEK, so it only runs in a user request. |
| 10 Home | n/a. |
| 11 UI routes | `/reset-password`, delete-account modal. |
| 12 Tests | `test_reset_purge.py`, `test_user_encryption.py`, `api/tests/unit/test_user_crypto.py`, `test_encryption.py`. |
| 13 Docs | `CLAUDE.md` "Per-user encryption". |

Gaps: no delete-account test, test SQLite doesn't enforce foreign keys,
TrueLayer tokens aren't revoked on delete, privacy copy understates
plaintext fields. See [known-gaps.md](../known-gaps.md).
