"""Replace raw provider transaction types stored as categories (T-08-1).

TrueLayer's transaction_category (PURCHASE, DIRECT_DEBIT, CREDIT…) is a
transaction type, and sync used to store it as the category. Sync now maps it
(app.services.categorization.category_from_provider); this backfills the rows
already stored, with the same mapping:

  TRANSFER                              -> 'Transfers'
  a credit of any other known type     -> 'Income'   (from transaction_type only)
  everything else (incl. UNKNOWN)      -> NULL       ("Uncategorized")

Only rows with category_locked = false are touched, so a category the user set
by hand is never changed. Before changing anything, (id, old category) of every
row it changes is copied into a backup table; downgrade() restores from it
(again only on unlocked rows) and drops the table. Running the backfill again
changes nothing, because no raw type is left to match.

The mapping is copied here on purpose: a migration must keep doing what it did
when it shipped, whatever later happens to the app code.

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
Create Date: 2026-10-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BACKUP_TABLE = "category_backfill_t08_1"

RAW_TYPES = frozenset({
    "ATM", "BILL_PAYMENT", "CASH", "CASHBACK", "CHEQUE", "CORRECTION", "CREDIT",
    "DEBIT", "DIRECT_DEBIT", "DIVIDEND", "FEE", "FEE_CHARGE", "INTEREST", "OTHER",
    "PURCHASE", "STANDING_ORDER", "TRANSFER", "UNKNOWN",
})
_INCOME_TYPES = RAW_TYPES - {"TRANSFER", "UNKNOWN"}

_MATCH = "category_locked = :unlocked AND category IN :raw"

_COPY_TO_BACKUP = sa.text(
    f"INSERT INTO {BACKUP_TABLE} (transaction_id, old_category) "
    f"SELECT id, category FROM transactions WHERE {_MATCH}"
).bindparams(sa.bindparam("raw", expanding=True))

_MAP = sa.text(
    "UPDATE transactions SET category = CASE "
    "WHEN category = 'TRANSFER' THEN 'Transfers' "
    "WHEN transaction_type = 'credit' AND category IN :income THEN 'Income' "
    "ELSE NULL END "
    f"WHERE {_MATCH}"
).bindparams(sa.bindparam("raw", expanding=True), sa.bindparam("income", expanding=True))

_RESTORE = sa.text(
    "UPDATE transactions SET category = ("
    f"  SELECT b.old_category FROM {BACKUP_TABLE} b WHERE b.transaction_id = transactions.id"
    ") WHERE category_locked = :unlocked "
    f"AND id IN (SELECT transaction_id FROM {BACKUP_TABLE})"
)


def backfill(conn) -> int:
    """Back up, then map, every unlocked row whose category is a raw type.
    Returns the number of rows changed."""
    params = {"unlocked": False, "raw": sorted(RAW_TYPES)}
    conn.execute(_COPY_TO_BACKUP, params)
    return conn.execute(_MAP, {**params, "income": sorted(_INCOME_TYPES)}).rowcount


def backup_rows(conn) -> dict[str, str]:
    """{transaction id: old category} as held in the backup table."""
    rows = conn.execute(
        sa.select(sa.column("transaction_id", sa.Uuid()), sa.column("old_category"))
        .select_from(sa.table(BACKUP_TABLE))
    )
    return {str(tx_id): old for tx_id, old in rows}


def upgrade() -> None:
    op.create_table(
        BACKUP_TABLE,
        sa.Column(
            "transaction_id", sa.Uuid(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("old_category", sa.String(100), nullable=False),
    )
    backfill(op.get_bind())


def downgrade() -> None:
    op.get_bind().execute(_RESTORE, {"unlocked": False})
    op.drop_table(BACKUP_TABLE)
