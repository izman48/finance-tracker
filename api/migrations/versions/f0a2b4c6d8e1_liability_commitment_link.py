"""Link a liability to its repayment commitment (T-10-8).

Additive and schema-only: `liabilities.linked_commitment_id` (FK to
commitment_rules, ON DELETE SET NULL, unique: one liability per commitment)
`liabilities.commitment_created` (boolean, default false: whether opting
out may delete the commitment) and `commitment_rules.ends_on` (the last
date a commitment can fall on). No row is written, so nothing moves and the previous
release ignores them. Downgrade drops them.

Revision ID: f0a2b4c6d8e1
Revises: f0a2b4c6d8e0
Create Date: 2026-10-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0a2b4c6d8e1"
down_revision: Union[str, None] = "f0a2b4c6d8e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("commitment_rules", sa.Column("ends_on", sa.Date(), nullable=True))
    op.add_column("liabilities", sa.Column("linked_commitment_id", sa.Uuid(), nullable=True))
    op.add_column(
        "liabilities", sa.Column("commitment_created", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_liabilities_linked_commitment_id_commitment_rules", "liabilities", "commitment_rules",
        ["linked_commitment_id"], ["id"], ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_liabilities_linked_commitment_id", "liabilities", ["linked_commitment_id"])


def downgrade() -> None:
    op.drop_constraint("uq_liabilities_linked_commitment_id", "liabilities", type_="unique")
    op.drop_constraint("fk_liabilities_linked_commitment_id_commitment_rules", "liabilities", type_="foreignkey")
    op.drop_column("liabilities", "commitment_created")
    op.drop_column("liabilities", "linked_commitment_id")
    op.drop_column("commitment_rules", "ends_on")
