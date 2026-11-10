"""Repayment marks (T-03-3 P1).

Additive: a new table; the previous release ignores it. The amount and label
are DEK-encrypted (text). Exactly one of spend or category per mark (a
check), one active mark per credit and spend and per credit and category
(partial unique indexes). The user and both transactions cascade.

Revision ID: 3c6965e7da5d
Revises: 4c697666e934
Create Date: 2026-11-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3c6965e7da5d"
down_revision: Union[str, None] = "4c697666e934"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repayment_marks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credit_transaction_id", sa.Uuid(),
                  sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("spend_transaction_id", sa.Uuid(),
                  sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("amount", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_via", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "(spend_transaction_id IS NULL) <> (category IS NULL)", name="ck_repayment_marks_one_target",
        ),
    )
    op.create_index("ix_repayment_marks_user_id", "repayment_marks", ["user_id"])
    op.create_index("ix_repayment_marks_credit_transaction_id", "repayment_marks", ["credit_transaction_id"])
    op.create_index("ix_repayment_marks_spend_transaction_id", "repayment_marks", ["spend_transaction_id"])
    op.create_index(
        "uq_repayment_marks_credit_spend_active", "repayment_marks",
        ["credit_transaction_id", "spend_transaction_id"], unique=True, postgresql_where=sa.text("active"),
    )
    op.create_index(
        "uq_repayment_marks_credit_category_active", "repayment_marks",
        ["credit_transaction_id", "category"], unique=True, postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index("uq_repayment_marks_credit_category_active", table_name="repayment_marks")
    op.drop_index("uq_repayment_marks_credit_spend_active", table_name="repayment_marks")
    op.drop_index("ix_repayment_marks_spend_transaction_id", table_name="repayment_marks")
    op.drop_index("ix_repayment_marks_credit_transaction_id", table_name="repayment_marks")
    op.drop_index("ix_repayment_marks_user_id", table_name="repayment_marks")
    op.drop_table("repayment_marks")
