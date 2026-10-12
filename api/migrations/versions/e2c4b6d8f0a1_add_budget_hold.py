"""The hold on a budget paused or removed mid-cycle (T-09-4).

Additive: two nullable columns; the previous release ignores them.
held_remaining is DEK-encrypted (text).

Revision ID: e2c4b6d8f0a1
Revises: d1f3a5c7e9b0
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2c4b6d8f0a1"
down_revision: Union[str, None] = "d1f3a5c7e9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("budgets", sa.Column("held_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("budgets", sa.Column("held_remaining", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("budgets", "held_remaining")
    op.drop_column("budgets", "held_from")
