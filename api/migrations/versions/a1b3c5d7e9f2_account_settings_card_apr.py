"""Account settings: the card's APR (T-10-5, ux A2, sec A2).

Additive: one nullable column, DEK-encrypted (text), like the liability APR.
No row is written; the previous release ignores it. account_settings becomes
an encrypted table; its rows are already purged on key loss. The downgrade
drops the column.

Revision ID: a1b3c5d7e9f2
Revises: f0a2b4c6d8e1
Create Date: 2026-10-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b3c5d7e9f2"
down_revision: Union[str, None] = "f0a2b4c6d8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("account_settings", sa.Column("card_apr", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("account_settings", "card_apr")
