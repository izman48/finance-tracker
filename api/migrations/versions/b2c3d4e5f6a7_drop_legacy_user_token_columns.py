"""Drop legacy per-user TrueLayer token columns

Bank tokens now live on bank_connections (one row per connected bank), so the
old single-token columns on users are unused. Remove them.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("users", "truelayer_access_token")
    op.drop_column("users", "truelayer_refresh_token")
    op.drop_column("users", "truelayer_token_expires_at")


def downgrade() -> None:
    op.add_column("users", sa.Column("truelayer_access_token", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("truelayer_refresh_token", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("truelayer_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
