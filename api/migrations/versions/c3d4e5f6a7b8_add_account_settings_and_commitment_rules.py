"""Add account_settings and commitment_rules (cashflow foundation)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="excluded"),
        sa.Column("overdraft_limit", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("repayment_cadence", sa.String(length=20), nullable=True),
        sa.Column("repayment_interval_months", sa.Integer(), nullable=True),
        sa.Column("repayment_day", sa.Integer(), nullable=True),
        sa.Column("repayment_anchor_date", sa.Date(), nullable=True),
        sa.Column("repayment_strategy", sa.String(length=20), nullable=False, server_default="full_balance"),
        sa.Column("repayment_fixed_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("pay_from_account_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pay_from_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_index("ix_account_settings_user_id", "account_settings", ["user_id"])
    op.create_index("ix_account_settings_account_id", "account_settings", ["account_id"])

    op.create_table(
        "commitment_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("cadence", sa.String(length=20), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.Column("interval_months", sa.Integer(), nullable=True),
        sa.Column("next_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="detected"),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="suggested"),
        sa.Column("match_key", sa.String(length=255), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_commitment_rules_user_id", "commitment_rules", ["user_id"])
    op.create_index("ix_commitment_rules_match_key", "commitment_rules", ["match_key"])


def downgrade() -> None:
    op.drop_index("ix_commitment_rules_match_key", table_name="commitment_rules")
    op.drop_index("ix_commitment_rules_user_id", table_name="commitment_rules")
    op.drop_table("commitment_rules")
    op.drop_index("ix_account_settings_account_id", table_name="account_settings")
    op.drop_index("ix_account_settings_user_id", table_name="account_settings")
    op.drop_table("account_settings")
