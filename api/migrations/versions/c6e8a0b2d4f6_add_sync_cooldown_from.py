"""The bank sync cooldown, held in the database (T-08-22).

Additive: one nullable column; the previous release ignores it.

Revision ID: c6e8a0b2d4f6
Revises: d7e8f9a0b1c2
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6e8a0b2d4f6"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_sync_locks", sa.Column("cooldown_from", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("user_sync_locks", "cooldown_from")
