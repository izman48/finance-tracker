"""Rule packs + richer category rules + locked categories

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_packs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("share_code", sa.String(length=20), nullable=True),
        sa.Column("imported_from", sa.String(length=150), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("share_code"),
    )
    op.create_index(op.f("ix_rule_packs_user_id"), "rule_packs", ["user_id"])
    op.create_index(op.f("ix_rule_packs_share_code"), "rule_packs", ["share_code"])

    # category_rules: match_key becomes pattern, plus engine fields.
    op.alter_column("category_rules", "match_key", new_column_name="pattern")
    op.add_column("category_rules", sa.Column("pack_id", sa.Uuid(), nullable=True))
    op.add_column(
        "category_rules",
        sa.Column("match_type", sa.String(length=10), nullable=False, server_default="exact"),
    )
    op.add_column(
        "category_rules",
        sa.Column("match_field", sa.String(length=12), nullable=False, server_default="any"),
    )
    op.add_column(
        "category_rules",
        sa.Column("source", sa.String(length=10), nullable=False, server_default="learned"),
    )
    op.add_column(
        "category_rules",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_foreign_key(
        "fk_category_rules_pack", "category_rules", "rule_packs", ["pack_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_category_rules_pack_id"), "category_rules", ["pack_id"])
    # Imports may legitimately duplicate a (user, pattern) pair across packs.
    op.drop_constraint("uq_category_rule_user_key", "category_rules", type_="unique")

    op.add_column(
        "transactions",
        sa.Column("category_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("transactions", "category_locked")
    op.create_unique_constraint("uq_category_rule_user_key", "category_rules", ["user_id", "pattern"])
    op.drop_index(op.f("ix_category_rules_pack_id"), table_name="category_rules")
    op.drop_constraint("fk_category_rules_pack", "category_rules", type_="foreignkey")
    op.drop_column("category_rules", "enabled")
    op.drop_column("category_rules", "source")
    op.drop_column("category_rules", "match_field")
    op.drop_column("category_rules", "match_type")
    op.drop_column("category_rules", "pack_id")
    op.alter_column("category_rules", "pattern", new_column_name="match_key")
    op.drop_index(op.f("ix_rule_packs_share_code"), table_name="rule_packs")
    op.drop_index(op.f("ix_rule_packs_user_id"), table_name="rule_packs")
    op.drop_table("rule_packs")
