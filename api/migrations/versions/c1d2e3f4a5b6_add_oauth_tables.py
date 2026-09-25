"""OAuth 2.1 tables for remote MCP clients.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-09-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(64), primary_key=True),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("redirect_uris", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column(
            "client_id",
            sa.String(64),
            sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("scopes", sa.String(255), nullable=False),
        sa.Column("resource", sa.String(255), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("wrapped_dek", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_oauth_authorization_codes_user_id", "oauth_authorization_codes", ["user_id"])
    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "client_id",
            sa.String(64),
            sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.String(255), nullable=False),
        sa.Column("resource", sa.String(255), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("previous_refresh_token_hash", sa.String(64), nullable=True),
        sa.Column("wrapped_dek", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_oauth_grants_user_id", "oauth_grants", ["user_id"])
    op.create_index("ix_oauth_grants_client_id", "oauth_grants", ["client_id"])
    op.create_index("ix_oauth_grants_refresh_token_hash", "oauth_grants", ["refresh_token_hash"], unique=True)
    op.create_index(
        "ix_oauth_grants_previous_refresh_token_hash", "oauth_grants", ["previous_refresh_token_hash"]
    )


def downgrade() -> None:
    op.drop_table("oauth_grants")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_clients")
