"""Record who made each planned item: the app or Claude (T-08-6).

Additive: one NOT NULL column with a server default, so existing rows read
"web" and the previous release (which doesn't know the column) still runs.

Revision ID: 004fdf1183b6
Revises: e8f9a0b1c2d3
Create Date: 2026-10-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004fdf1183b6"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "planned_items",
        sa.Column("created_via", sa.String(10), nullable=False, server_default="web"),
    )


def downgrade() -> None:
    op.drop_column("planned_items", "created_via")
