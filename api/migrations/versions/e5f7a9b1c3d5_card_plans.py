"""Card instalment plans (T-12-5a, ADR-002 holding kind `card_plan`).

Additive: a new table `card_plans`. Name and amounts are DEK-encrypted text
(the server can't read them in a migration); ids, counts and dates are
plaintext. The card link is ON DELETE SET NULL, so a bank disconnect leaves
the plan as standalone debt rather than deleting it. Nothing existing
changes, and the previous release ignores the table. The downgrade drops it
and restores nothing, so no foreign key can break it (plans entered after
the upgrade are lost; their instalments were only ever projected).

Revision ID: e5f7a9b1c3d5
Revises: c3e5a7b9d1f4
Create Date: 2026-10-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f7a9b1c3d5"
down_revision: Union[str, None] = "c3e5a7b9d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "card_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("card_account_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),  # DEK-encrypted
        sa.Column("balance", sa.Text(), nullable=False),  # DEK-encrypted decimal
        sa.Column("instalment", sa.Text(), nullable=False),  # DEK-encrypted decimal
        sa.Column("fee", sa.Text(), nullable=False),  # DEK-encrypted decimal
        sa.Column("apr", sa.Text(), nullable=True),  # DEK-encrypted decimal
        sa.Column("instalments_remaining", sa.Integer(), nullable=False),
        sa.Column("next_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_card_plans_user_id", "card_plans", ["user_id"])
    op.create_index("ix_card_plans_card_account_id", "card_plans", ["card_account_id"])


def downgrade() -> None:
    op.drop_index("ix_card_plans_card_account_id", table_name="card_plans")
    op.drop_index("ix_card_plans_user_id", table_name="card_plans")
    op.drop_table("card_plans")
