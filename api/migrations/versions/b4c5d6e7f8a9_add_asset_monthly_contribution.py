"""Add assets.monthly_contribution: planned monthly saving into an asset

The unified projection adds it to the asset each month (compounding at the
asset's rate). The cash side is already measured — contributions to external
platforms show up inside "average everyday spending" — so declaring the
destination recovers that money into wealth instead of counting it as
consumption. It's an amount describing the user's saving behaviour, so it's
DEK-encrypted like valuation and flow amounts.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("monthly_contribution", sa.Text(), nullable=True),  # DEK-encrypted decimal
    )


def downgrade() -> None:
    op.drop_column("assets", "monthly_contribution")
