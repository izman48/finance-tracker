"""Budgets (T-09-2).

Additive: a new table; the previous release ignores it. The limit is
DEK-encrypted (text). One active budget per user and category, by a partial
unique index.

Revision ID: d1f3a5c7e9b0
Revises: c6e8a0b2d4f6
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1f3a5c7e9b0"
down_revision: Union[str, None] = "c6e8a0b2d4f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("limit_pounds", sa.Text(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_via", sa.String(10), nullable=False, server_default="web"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_budgets_user_id", "budgets", ["user_id"])
    op.create_index(
        "uq_budgets_user_category_active", "budgets", ["user_id", "category"], unique=True,
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index("uq_budgets_user_category_active", table_name="budgets")
    op.drop_index("ix_budgets_user_id", table_name="budgets")
    op.drop_table("budgets")
