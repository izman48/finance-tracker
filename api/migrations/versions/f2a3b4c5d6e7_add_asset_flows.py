"""Add asset_flows: recorded deposits/withdrawals on manual assets

Lets the net-worth decomposition tell saving apart from market growth:
growth in a window = Δvaluation − Σflows. Amounts are DEK-encrypted (Text),
like the valuations they sit beside.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_flows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Text(), nullable=False),  # DEK-encrypted decimal
        sa.Column("flow_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_flows_asset_id", "asset_flows", ["asset_id"])
    op.create_index("ix_asset_flows_flow_date", "asset_flows", ["flow_date"])


def downgrade() -> None:
    op.drop_index("ix_asset_flows_flow_date", table_name="asset_flows")
    op.drop_index("ix_asset_flows_asset_id", table_name="asset_flows")
    op.drop_table("asset_flows")
