"""Budget nudges, once per budget per cycle (T-09-4b).

Additive: a new table; the previous release ignores it. No user data in
clear: the nudge text is built when shown.

Revision ID: f4d6e8a0c2b3
Revises: e2c4b6d8f0a1
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4d6e8a0c2b3"
down_revision: Union[str, None] = "e2c4b6d8f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budget_nudges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_id", sa.Uuid(), sa.ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cycle_start", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("budget_id", "cycle_start", "kind", name="uq_budget_nudges_once"),
    )
    op.create_index("ix_budget_nudges_user_id", "budget_nudges", ["user_id"])
    op.create_index("ix_budget_nudges_budget_id", "budget_nudges", ["budget_id"])


def downgrade() -> None:
    op.drop_index("ix_budget_nudges_budget_id", table_name="budget_nudges")
    op.drop_index("ix_budget_nudges_user_id", table_name="budget_nudges")
    op.drop_table("budget_nudges")
