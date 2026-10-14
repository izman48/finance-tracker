"""Account settings: the instalment-card flag (T-10-4a).

Additive: one plaintext boolean, NOT NULL with a server default of false, so
every existing row is a standard card and the previous release ignores the
column. Only an instalment-type card may use the `scheduled` strategy; cards
already on it keep working and show a "fix this" notice (no data changes).

Revision ID: e9f1a3b5c7d9
Revises: d8e0f2a4b6c8
Create Date: 2026-10-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9f1a3b5c7d9"
down_revision: Union[str, None] = "d8e0f2a4b6c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "account_settings",
        sa.Column("instalment_card", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("account_settings", "instalment_card")
