"""Add counts-as overrides: transactions.counts_as_override + category_rules.counts_as

The automatic noise classification (paired transfers, card-repayment
indicators) can't see transfers to unconnected destinations — ISA direct
debits, savings at other banks — so they pollute spending figures and the
projection's derived surplus. These columns let the user state the truth:
per transaction, and per rule so future syncs mark recurring transfers
automatically. Values: spending | transfer | card_payment (a small enum of
our own labels, not user text — plaintext).

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("counts_as_override", sa.String(20), nullable=True),
    )
    op.add_column(
        "category_rules",
        sa.Column("counts_as", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("category_rules", "counts_as")
    op.drop_column("transactions", "counts_as_override")
