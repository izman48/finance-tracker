"""Planned items can be marked as a card payment (T-12-4a).

Additive: one plaintext boolean, `planned_items.is_card_payment`, default
false, so every existing item stays as it is and nothing moves until the
user ticks it; the previous release ignores the column. The downgrade drops
it (rollback: downgrade first, then revert).

Revision ID: f8c0e2a4b6d9
Revises: c3e5a7b9d1f4
Create Date: 2026-10-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8c0e2a4b6d9"
down_revision: Union[str, None] = "c3e5a7b9d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("planned_items") as batch:
        batch.add_column(sa.Column("is_card_payment", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("planned_items") as batch:
        batch.drop_column("is_card_payment")
