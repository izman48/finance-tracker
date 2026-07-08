"""Add is_payday flag to commitment_rules

Lets the user designate which income is their payday, so safe-to-spend, the
forecast and the since-payday window key off it instead of the nearest credit.

Revision ID: e1f2a3b4c5d6
Revises: a8b9c0d1e2f3
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "commitment_rules",
        sa.Column(
            "is_payday",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("commitment_rules", "is_payday")
