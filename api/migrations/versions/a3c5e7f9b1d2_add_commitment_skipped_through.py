"""A late income the user skipped (T-08-23).

Additive: one nullable column; the previous release ignores it.

Revision ID: a3c5e7f9b1d2
Revises: 5f7b38f4dc78
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3c5e7f9b1d2"
down_revision: Union[str, None] = "5f7b38f4dc78"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("commitment_rules", sa.Column("skipped_through", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("commitment_rules", "skipped_through")
