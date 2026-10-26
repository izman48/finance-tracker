"""What else a Claude write changed, for undo (#256: a rule edit's backfill).

Additive: one nullable column; the previous release ignores it.

Revision ID: 4c697666e934
Revises: d7e9f1a3b5c7
Create Date: 2026-10-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4c697666e934"
down_revision: Union[str, None] = "d7e9f1a3b5c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_entries", sa.Column("side_effects", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_entries", "side_effects")
