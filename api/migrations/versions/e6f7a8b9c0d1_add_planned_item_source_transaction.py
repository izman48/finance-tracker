"""Link a planned item to the transaction it was financed from

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "planned_items",
        sa.Column("source_transaction_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_planned_items_source_transaction_id",
        "planned_items",
        ["source_transaction_id"],
    )
    op.create_foreign_key(
        "fk_planned_items_source_transaction_id",
        "planned_items",
        "transactions",
        ["source_transaction_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_planned_items_source_transaction_id", "planned_items", type_="foreignkey")
    op.drop_index("ix_planned_items_source_transaction_id", table_name="planned_items")
    op.drop_column("planned_items", "source_transaction_id")
