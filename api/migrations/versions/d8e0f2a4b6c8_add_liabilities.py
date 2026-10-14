"""Add liabilities: loans, retail finance and BNPL the user enters (T-10-7a).

A new table only, so nothing existing changes and the previous release runs
on it unchanged. Lender, balance, APR and payment are DEK-encrypted (Text);
kind, cadence, dates and the opt-out flag are plaintext. Rows cascade from
users (account deletion). Downgrade drops the table.

Revision ID: d8e0f2a4b6c8
Revises: b6c8d0e2f4a6
Create Date: 2026-10-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8e0f2a4b6c8"
down_revision: Union[str, None] = "b6c8d0e2f4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "liabilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("lender", sa.Text(), nullable=False),  # DEK-encrypted
        sa.Column("balance", sa.Text(), nullable=False),  # DEK-encrypted decimal
        sa.Column("balance_as_of", sa.Date(), nullable=False),
        sa.Column("apr", sa.Text(), nullable=False),  # DEK-encrypted decimal
        sa.Column("payment", sa.Text(), nullable=True),  # DEK-encrypted decimal
        sa.Column("cadence", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("opted_out", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_liabilities_user_id", "liabilities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_liabilities_user_id", table_name="liabilities")
    op.drop_table("liabilities")
