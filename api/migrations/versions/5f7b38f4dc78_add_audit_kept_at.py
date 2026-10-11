"""When the user kept a Claude change, and what they set by hand since (T-08-20).

Additive: two nullable columns; the previous release ignores them.

Revision ID: 5f7b38f4dc78
Revises: 004fdf1183b6
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5f7b38f4dc78"
down_revision: Union[str, None] = "004fdf1183b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_entries", sa.Column("kept_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_entries", sa.Column("user_set_fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_entries", "user_set_fields")
    op.drop_column("audit_entries", "kept_at")
