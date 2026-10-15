"""Soft delete of planned items on the web (T-12-9b).

Additive: one nullable plaintext timestamp, `planned_items.deleted_at`. No
row is written; existing items stay as they are, and the previous release
ignores the column (it still filters on `active`). The downgrade drops it.
An item soft-deleted under this release is inactive, so after a downgrade
it still counts nowhere (rollback: downgrade first, then revert).

Revision ID: e6b8d0f2a4c7
Revises: e5f7a9b1c3d5
Create Date: 2026-10-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6b8d0f2a4c7"
down_revision: Union[str, None] = "e5f7a9b1c3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("planned_items") as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("planned_items") as batch:
        batch.drop_column("deleted_at")
