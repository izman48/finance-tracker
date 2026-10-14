"""Clear repayment settings on non-credit accounts (T-10-4b).

The old settings form sent repayment defaults (end_of_month, full_balance,
3 instalments) for every role, so current and savings accounts carry
repayment fields. Nothing reads them: repayments only come from credit
accounts. Since T-10-4a the API refuses them on non-credit accounts; this
clears the ones already stored.

Rules (sec, T-10-4b):
- Only plaintext `account_settings` columns are read or written. No encrypted
  column, and `repayment_schedule_items` is never touched.
- Only rows whose stored role is `spending` or `savings`. `credit` and
  `excluded` rows are left alone, so a card the user parked keeps its plan.
- "Cleared" is the state of a fresh row: every repayment field NULL,
  `repayment_strategy` = 'full_balance' (its NOT NULL default) and
  `instalment_card` = false.
- Before clearing, the old values (account_id and the repayment columns, all
  plaintext) go to a backup table, to be dropped in a later sprint. The
  downgrade restores them on rows still in the cleared state (a setting the
  user changed since is kept) and drops the table.
- Idempotent: a second run matches nothing. Alembic runs it in the boot
  transaction. Logs counts only, never ids.

Revision ID: f0a2b4c6d8e0
Revises: e9f1a3b5c7d9
Create Date: 2026-10-14
"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0a2b4c6d8e0"
down_revision: Union[str, None] = "e9f1a3b5c7d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

BACKUP_TABLE = "account_repayment_backup_t10_4b"
REPAYMENT_COLUMNS = (
    "repayment_cadence", "repayment_interval_months", "repayment_day", "repayment_anchor_date",
    "repayment_strategy", "repayment_fixed_amount", "repayment_installments", "pay_from_account_id",
    "instalment_card",
)
# Copied on purpose: a migration keeps doing what it did when it shipped.
_ROLES = ("spending", "savings", "credit", "excluded")
_STRATEGIES = ("full_balance", "fixed", "installments", "minimum_percent", "scheduled", "statement_balance")
_CADENCES = ("monthly", "end_of_month", "every_n_months", "weekly", "card_due_date")

_CLEARED = (
    "repayment_cadence IS NULL AND repayment_interval_months IS NULL AND repayment_day IS NULL "
    "AND repayment_anchor_date IS NULL AND repayment_fixed_amount IS NULL "
    "AND repayment_installments IS NULL AND pay_from_account_id IS NULL "
    "AND repayment_strategy = 'full_balance' AND instalment_card = :no"
)
_MATCH = f"role IN ('spending', 'savings') AND NOT ({_CLEARED})"
_COLUMNS = ", ".join(REPAYMENT_COLUMNS)

_COPY_TO_BACKUP = sa.text(
    f"INSERT INTO {BACKUP_TABLE} (account_id, {_COLUMNS}) "
    f"SELECT account_id, {_COLUMNS} FROM account_settings WHERE {_MATCH} "
    f"AND account_id NOT IN (SELECT account_id FROM {BACKUP_TABLE})"
)
_CLEAR = sa.text(
    "UPDATE account_settings SET repayment_cadence = NULL, repayment_interval_months = NULL, "
    "repayment_day = NULL, repayment_anchor_date = NULL, repayment_fixed_amount = NULL, "
    "repayment_installments = NULL, pay_from_account_id = NULL, "
    f"repayment_strategy = 'full_balance', instalment_card = :no WHERE {_MATCH}"
)
_RESTORE = sa.text(
    "UPDATE account_settings SET "
    + ", ".join(
        f"{c} = (SELECT b.{c} FROM {BACKUP_TABLE} b WHERE b.account_id = account_settings.account_id)"
        for c in REPAYMENT_COLUMNS
    )
    + f" WHERE account_id IN (SELECT account_id FROM {BACKUP_TABLE}) "
    f"AND role IN ('spending', 'savings') AND {_CLEARED}"
)


def _count(conn, where: str, **params) -> int:
    return conn.execute(sa.text(f"SELECT count(*) FROM account_settings WHERE {where}"), params).scalar()


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"  # fixed constants above, never input


def clear(conn) -> int:
    """Back up, then clear, the repayment fields of non-credit rows. Logs
    counts only. Returns the number of rows changed."""
    matched = _count(conn, _MATCH, no=False)
    non_enum = _count(
        conn,
        f"role NOT IN {_in(_ROLES)} OR repayment_strategy NOT IN {_in(_STRATEGIES)} "
        f"OR (repayment_cadence IS NOT NULL AND repayment_cadence NOT IN {_in(_CADENCES)})",
    )
    credit_unknown = _count(
        conn,
        f"role = 'credit' AND (repayment_strategy NOT IN {_in(_STRATEGIES)} "
        f"OR (repayment_cadence IS NOT NULL AND repayment_cadence NOT IN {_in(_CADENCES)}))",
    )
    conn.execute(_COPY_TO_BACKUP, {"no": False})
    changed = conn.execute(_CLEAR, {"no": False}).rowcount
    logger.info(
        "Clearing repayment settings on non-credit accounts: matched=%d changed=%d "
        "non_enum_rows=%d credit_rows_with_unknown_cadence_or_strategy=%d",
        matched, changed, non_enum, credit_unknown,
    )
    return changed


def upgrade() -> None:
    op.create_table(
        BACKUP_TABLE,
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("repayment_cadence", sa.String(20), nullable=True),
        sa.Column("repayment_interval_months", sa.Integer(), nullable=True),
        sa.Column("repayment_day", sa.Integer(), nullable=True),
        sa.Column("repayment_anchor_date", sa.Date(), nullable=True),
        sa.Column("repayment_strategy", sa.String(20), nullable=False),
        sa.Column("repayment_fixed_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("repayment_installments", sa.Integer(), nullable=True),
        sa.Column("pay_from_account_id", sa.Uuid(), nullable=True),
        sa.Column("instalment_card", sa.Boolean(), nullable=False),
    )
    clear(op.get_bind())


def downgrade() -> None:
    op.get_bind().execute(_RESTORE, {"no": False})
    op.drop_table(BACKUP_TABLE)
