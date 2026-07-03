"""Encrypt derived tables: commitments, rules, planned items, assets

Follow-up to f7a8b9c0d1e2: features that copy data out of transactions were
leaking it in plaintext — commitment labels/amounts, learned rule patterns
(literally merchant names), planned-item names/amounts, scheduled repayment
amounts, and manual asset names/values. All are now DEK-encrypted. Rule packs
gain a plaintext share snapshot written at share time, since importers never
hold the owner's key.

Existing rows predate encryption and can't be read under the new scheme, so
they are removed (same rationale as f7a8b9c0d1e2; the planned prod reset makes
this moot in practice).

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW_ENCRYPTED = (
    "commitment_rules",
    "planned_items",
    "repayment_schedule_items",
    "category_rules",
    "asset_valuations",
    "assets",
)


def upgrade() -> None:
    # Plaintext rows are unreadable under the new scheme; clear them first
    # (order respects FKs: valuations before assets, rules before nothing).
    for table in _NOW_ENCRYPTED:
        op.execute(f"DELETE FROM {table}")

    # commitment_rules: label/amount/match_key become ciphertext Text. The
    # match_key index goes — non-deterministic ciphertext can't be looked up.
    op.drop_index("ix_commitment_rules_match_key", table_name="commitment_rules")
    op.alter_column("commitment_rules", "label", type_=sa.Text())
    op.alter_column("commitment_rules", "amount", type_=sa.Text(), postgresql_using="amount::text")
    op.alter_column("commitment_rules", "match_key", type_=sa.Text())

    op.alter_column("planned_items", "name", type_=sa.Text())
    for col in ("amount", "total_amount", "apr", "fee_amount"):
        op.alter_column("planned_items", col, type_=sa.Text(), postgresql_using=f"{col}::text")

    op.alter_column(
        "repayment_schedule_items", "amount", type_=sa.Text(), postgresql_using="amount::text"
    )

    op.alter_column("category_rules", "pattern", type_=sa.Text())
    op.add_column("rule_packs", sa.Column("share_snapshot", sa.Text(), nullable=True))

    op.alter_column("assets", "name", type_=sa.Text())
    op.alter_column("asset_valuations", "value", type_=sa.Text(), postgresql_using="value::text")


def downgrade() -> None:
    for table in _NOW_ENCRYPTED:
        op.execute(f"DELETE FROM {table}")

    op.alter_column("asset_valuations", "value", type_=sa.Numeric(14, 2), postgresql_using="value::numeric")
    op.alter_column("assets", "name", type_=sa.String(100))

    op.drop_column("rule_packs", "share_snapshot")
    op.alter_column("category_rules", "pattern", type_=sa.String(255))

    op.alter_column("repayment_schedule_items", "amount", type_=sa.Numeric(12, 2), postgresql_using="amount::numeric")

    op.alter_column("planned_items", "fee_amount", type_=sa.Numeric(12, 2), postgresql_using="fee_amount::numeric")
    op.alter_column("planned_items", "apr", type_=sa.Numeric(6, 3), postgresql_using="apr::numeric")
    op.alter_column("planned_items", "total_amount", type_=sa.Numeric(12, 2), postgresql_using="total_amount::numeric")
    op.alter_column("planned_items", "amount", type_=sa.Numeric(12, 2), postgresql_using="amount::numeric")
    op.alter_column("planned_items", "name", type_=sa.String(255))

    op.alter_column("commitment_rules", "match_key", type_=sa.String(255))
    op.alter_column("commitment_rules", "amount", type_=sa.Numeric(12, 2), postgresql_using="amount::numeric")
    op.alter_column("commitment_rules", "label", type_=sa.String(255))
    op.create_index("ix_commitment_rules_match_key", "commitment_rules", ["match_key"])
