"""Drop holdings pricing: instruments, instrument_prices, Asset.instrument_id + units

Live holdings pricing was reverted: every free market-data tier (crypto, US,
LSE) is personal/non-commercial-licensed, which doesn't fit nilu.'s paid
direction. Holdings are valued manually (the enter-a-value flow) — no licensed
price data is fetched or stored. This drops the schema that fed live pricing.

Production already ran d6e7f8a9b0c1, so this is a forward migration that undoes
it (we can't delete d6e7f8a9b0c1 or Alembic loses the stamped revision). Any
`units` a user entered on a linked holding is dropped; the asset itself and its
valuations (net-worth history) are untouched.

Revision ID: a9b0c1d2e3f4
Revises: d6e7f8a9b0c1
Create Date: 2026-07-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("fk_assets_instrument_id", "assets", type_="foreignkey")
    op.drop_column("assets", "units")
    op.drop_column("assets", "instrument_id")
    op.drop_index("ix_instrument_prices_as_of", table_name="instrument_prices")
    op.drop_index("ix_instrument_prices_instrument_id", table_name="instrument_prices")
    op.drop_table("instrument_prices")
    op.drop_index("ix_instruments_symbol", table_name="instruments")
    op.drop_table("instruments")


def downgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_ref", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=4), nullable=False, server_default="GBP"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_ref", name="uq_instrument_provider_ref"),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"])

    op.create_table(
        "instrument_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("price_gbp", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("price_native", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_instrument_prices_instrument_id", "instrument_prices", ["instrument_id"])
    op.create_index("ix_instrument_prices_as_of", "instrument_prices", ["as_of"])

    op.add_column("assets", sa.Column("instrument_id", sa.Uuid(), nullable=True))
    op.add_column("assets", sa.Column("units", sa.Text(), nullable=True))  # DEK-encrypted
    op.create_foreign_key(
        "fk_assets_instrument_id", "assets", "instruments", ["instrument_id"], ["id"], ondelete="SET NULL"
    )
