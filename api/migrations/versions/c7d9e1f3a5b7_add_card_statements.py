"""Card statements (T-10-1).

Additive: one new table; the previous release ignores it. Statement balance
and minimum due are DEK-encrypted (text). The unique constraint uses
plaintext columns only: one row per card per statement date per source
(manual or provider). Both foreign keys cascade, so delete-account and
deleting a card remove its statements.

Revision ID: c7d9e1f3a5b7
Revises: b6c8d0e2f4a6
Create Date: 2026-10-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d9e1f3a5b7"
down_revision: Union[str, None] = "b6c8d0e2f4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "card_statements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("statement_balance", sa.Text(), nullable=False),
        sa.Column("minimum_due", sa.Text(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "statement_date", "source", name="uq_card_statements_period_source"),
    )
    op.create_index("ix_card_statements_user_id", "card_statements", ["user_id"])
    op.create_index("ix_card_statements_account_id", "card_statements", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_card_statements_account_id", table_name="card_statements")
    op.drop_index("ix_card_statements_user_id", table_name="card_statements")
    op.drop_table("card_statements")
