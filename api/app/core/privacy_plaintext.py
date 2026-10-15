"""Every database column that is stored unencrypted, grouped the way the
privacy page describes them (T-12-13).

Financial data (amounts, descriptions, merchants, names, balances, labels,
bank tokens) is encrypted under the user's key. The columns below are not:
the app needs them in plain form to sort, filter, schedule or sign in.
Primary keys and foreign keys (record ids and the links between records)
are left out; the page says so in general terms.

`tests/unit/test_privacy_plaintext.py` fails when a plaintext column is
added without being listed here, and `.github/scripts/check_privacy_copy.py`
fails when a phrase below is missing from the privacy page
(`ui/src/pages/BetaInfoPage.tsx`). Keep the phrases plain and exact.
"""

# Group key -> the exact words the privacy page shows for it.
PRIVACY_PHRASES: dict[str, str] = {
    "email": "your email address",
    "dates": "dates and times, such as when a transaction, payment, statement or plan falls due and when a record was created or changed",
    "categories": "categories, including budget categories and the category each rule sets; rule packs' names and descriptions; and, for a pack you share, a copy of its rules (patterns included) so others can import it. Your own rules' patterns are encrypted",
    "types": "the type and settings of each record and its on/off switches, such as how often a bill repeats, whether it is your payday, an account's role, or a record's status",
    "card_settings": "overdraft limits and card repayment settings, including a fixed repayment amount you choose",
    "counts": "the growth rate you set for a holding, and how many payments are left or planned",
    "bank_refs": "your bank's own reference numbers for accounts and transactions, and their currency",
    "claude": "details of Claude connections you approve: the app's name, its web address and the access you granted",
    "protected": "your password and keys, only in protected form: a salted password hash, keys wrapped under your password, your recovery code or a Claude connection's token (we keep only a hash of that token), and hashes of access tokens",
    "ids": "internal reference numbers that link one record to another",
}

# Group key -> {table: (columns)}.
PLAINTEXT: dict[str, dict[str, tuple[str, ...]]] = {
    "email": {"users": ("email",)},
    "dates": {
        "account_settings": ("created_at", "updated_at"),
        "accounts": ("balance_updated_at", "created_at", "updated_at"),
        "asset_flows": ("flow_date", "created_at"),
        "asset_valuations": ("valued_at", "created_at"),
        "assets": ("created_at", "updated_at"),
        "audit_entries": ("undone_at", "kept_at", "created_at"),
        "bank_connections": ("token_expires_at", "last_synced_at", "created_at", "updated_at"),
        "budget_changes": ("effective_at",),
        "budget_cycle_snapshots": ("cycle_start", "cycle_end", "written_at"),
        "budget_nudges": ("cycle_start", "fired_at", "dismissed_at"),
        "budgets": ("held_from", "created_at", "updated_at"),
        "card_plans": ("next_date", "created_at", "updated_at"),
        "card_statements": ("statement_date", "due_date", "created_at", "updated_at"),
        "category_rules": ("created_at", "updated_at"),
        "commitment_links": ("created_on",),
        "commitment_rules": ("next_date", "skipped_through", "ends_on", "created_at", "updated_at"),
        "liabilities": ("balance_as_of", "start_date", "end_date", "created_at", "updated_at"),
        "oauth_authorization_codes": ("expires_at",),
        "oauth_clients": ("created_at",),
        "oauth_grants": ("created_at", "last_used_at", "expires_at", "revoked_at"),
        "planned_items": ("start_date", "end_date", "deleted_at", "created_at", "updated_at"),
        "repayment_schedule_items": ("due_date", "created_at", "updated_at"),
        "rule_packs": ("created_at", "updated_at"),
        "transactions": ("transaction_date", "created_at"),
        "user_sync_locks": ("locked_until", "cooldown_from"),
        "users": ("created_at", "updated_at"),
        "write_idempotency": ("created_at",),
    },
    "categories": {
        "budgets": ("category",),
        "category_rules": ("category",),
        "rule_packs": ("name", "description", "share_code", "share_snapshot", "imported_from"),
        "transactions": ("category", "subcategory"),
    },
    "types": {
        "account_settings": ("role",),
        "accounts": ("account_type",),
        "assets": ("asset_type",),
        "audit_entries": ("kind", "tool", "target_kind", "created_target", "user_set_fields"),
        "budget_changes": ("paused", "active"),
        "budget_cycle_snapshots": ("paused",),
        "budget_nudges": ("kind",),
        "budgets": ("paused", "active", "created_via"),
        "card_statements": ("source",),
        "category_rules": ("match_type", "match_field", "counts_as", "source", "enabled"),
        "commitment_links": ("role", "commitment_created"),
        "commitment_rules": ("direction", "cadence", "source", "status", "is_payday", "card_link_source"),
        "liabilities": ("kind", "cadence", "commitment_created", "opted_out"),
        "oauth_authorization_codes": ("session_version",),
        "oauth_grants": ("session_version",),
        "planned_items": ("direction", "kind", "cadence", "active", "is_card_payment", "created_via"),
        "rule_packs": ("enabled",),
        "transactions": ("transaction_type", "category_locked", "counts_as_override", "counts_as_locked", "is_recurring"),
        "users": ("session_version",),
    },
    "card_settings": {
        "account_settings": (
            "overdraft_limit", "repayment_cadence", "repayment_interval_months", "repayment_day",
            "repayment_anchor_date", "repayment_strategy", "repayment_fixed_amount", "repayment_installments",
            "instalment_card",
        ),
    },
    "counts": {
        "assets": ("assumed_growth_pct",),
        "card_plans": ("instalments_remaining",),
        "commitment_rules": ("interval_days", "interval_months"),
        "planned_items": ("interval_days", "interval_months", "installments"),
    },
    "bank_refs": {
        "accounts": ("external_id", "currency"),
        "transactions": ("external_id", "currency"),
    },
    "claude": {
        "audit_entries": ("client_id",),
        "oauth_authorization_codes": ("redirect_uri", "code_challenge", "scopes", "resource"),
        "oauth_clients": ("client_name", "redirect_uris"),
        "oauth_grants": ("scopes", "resource"),
    },
    "protected": {
        "oauth_authorization_codes": ("wrapped_dek",),
        "oauth_grants": ("refresh_token_hash", "previous_refresh_token_hash", "wrapped_dek"),
        "users": ("hashed_password", "wrapped_dek", "dek_salt", "recovery_wrapped_dek", "recovery_salt"),
    },
    "ids": {
        "audit_entries": ("target_id", "batch_id"),
        "transactions": ("recurring_group_id",),
        "user_sync_locks": ("lock_token",),
        "write_idempotency": ("key", "request_hash"),
    },
}
