"""Add assets.assumed_growth_pct: per-asset projection assumption

Lets the unified net-worth projection grow each asset at its own stated rate
(ISA 5%, property 3%, a liability held flat or shrinking). It's an assumption
the user types, not wealth data — plaintext, like asset_type.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("assumed_growth_pct", sa.Numeric(5, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assets", "assumed_growth_pct")
