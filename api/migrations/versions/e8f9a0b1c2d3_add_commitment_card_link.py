"""Stored link from a commitment to the credit card it repays (T-08-8).

Schema only, and additive: a nullable `card_account_id` FK (ON DELETE SET
NULL, indexed) and a nullable `card_link_source`. No data is written here.
Commitment labels and account names are encrypted with each user's key, which
a migration never has, so existing commitments are linked lazily at request
time (app/services/analytics/card_links.py).

Batch mode so the same migration runs on SQLite in tests; on Postgres it is
plain ALTER TABLE.

Revision ID: e8f9a0b1c2d3
Revises: c1d2e3f4a5b6
Create Date: 2026-10-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "fk_commitment_rules_card_account_id_accounts"
_INDEX = "ix_commitment_rules_card_account_id"


def upgrade() -> None:
    with op.batch_alter_table("commitment_rules") as batch:
        batch.add_column(sa.Column("card_account_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("card_link_source", sa.String(10), nullable=True))
        batch.create_foreign_key(_FK, "accounts", ["card_account_id"], ["id"], ondelete="SET NULL")
        batch.create_index(_INDEX, ["card_account_id"])


def downgrade() -> None:
    with op.batch_alter_table("commitment_rules") as batch:
        batch.drop_index(_INDEX)
        batch.drop_constraint(_FK, type_="foreignkey")
        batch.drop_column("card_link_source")
        batch.drop_column("card_account_id")
