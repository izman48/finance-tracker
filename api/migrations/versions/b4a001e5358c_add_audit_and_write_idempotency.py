"""Audit trail and idempotency records for Claude's planning writes (T-08-3b).

Additive: two new tables, nothing existing changes, so the previous release
runs on this schema. downgrade() drops both (the audit trail is lost, which
is acceptable only because nothing writes to it before this release).

Revision ID: b4a001e5358c
Revises: c1d2e3f4a5b6
Create Date: 2026-10-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4a001e5358c"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("tool", sa.String(50), nullable=False),
        sa.Column("target_kind", sa.String(20), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_label", sa.Text(), nullable=False),
        sa.Column("changes", sa.Text(), nullable=False),
        sa.Column("created_target", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("grant_id", sa.Uuid(), sa.ForeignKey("oauth_grants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("client_id", sa.String(64), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("undoes_id", sa.Uuid(), sa.ForeignKey("audit_entries.id"), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # The audit list pages newest first per user.
    op.create_index("ix_audit_entries_user_created", "audit_entries", ["user_id", "created_at", "id"])
    op.create_table(
        "write_idempotency",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("audit_id", sa.Uuid(), sa.ForeignKey("audit_entries.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "key", name="uq_write_idempotency_user_key"),
    )


def downgrade() -> None:
    op.drop_table("write_idempotency")
    op.drop_index("ix_audit_entries_user_created", table_name="audit_entries")
    op.drop_table("audit_entries")
