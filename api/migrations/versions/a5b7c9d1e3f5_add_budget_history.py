"""Budget history: the change log and per-cycle snapshots (T-09-3).

Additive: two new tables; the previous release ignores them. Limits and
spend are DEK-encrypted (text). Existing budgets get their first change row
lazily, at request time with the user's key (an encrypted limit can't be
read here).

Revision ID: a5b7c9d1e3f5
Revises: f4d6e8a0c2b3
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a5b7c9d1e3f5"
down_revision: Union[str, None] = "f4d6e8a0c2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budget_changes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_id", sa.Uuid(), sa.ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("limit_pounds", sa.Text(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_budget_changes_user_id", "budget_changes", ["user_id"])
    op.create_index("ix_budget_changes_budget_id", "budget_changes", ["budget_id"])
    op.create_table(
        "budget_cycle_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_id", sa.Uuid(), sa.ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cycle_start", sa.Date(), nullable=False),
        sa.Column("cycle_end", sa.Date(), nullable=False),
        sa.Column("limit_pounds", sa.Text(), nullable=False),
        sa.Column("spent", sa.Text(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("written_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("budget_id", "cycle_start", name="uq_budget_snapshots_cycle"),
    )
    op.create_index("ix_budget_cycle_snapshots_user_id", "budget_cycle_snapshots", ["user_id"])
    op.create_index("ix_budget_cycle_snapshots_budget_id", "budget_cycle_snapshots", ["budget_id"])


def downgrade() -> None:
    op.drop_index("ix_budget_cycle_snapshots_budget_id", table_name="budget_cycle_snapshots")
    op.drop_index("ix_budget_cycle_snapshots_user_id", table_name="budget_cycle_snapshots")
    op.drop_table("budget_cycle_snapshots")
    op.drop_index("ix_budget_changes_budget_id", table_name="budget_changes")
    op.drop_index("ix_budget_changes_user_id", table_name="budget_changes")
    op.drop_table("budget_changes")
