"""OAuth 2.1 state for remote MCP clients (see services/oauth.py).

Secrets (authorization codes, refresh tokens) are never stored: only their
SHA-256 for lookup, plus the user's DEK wrapped under a key derived from the
secret itself — so these tables, like the rest of the database, can't unlock
anyone's data without something only the client holds.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OAuthClient(Base):
    """A dynamically registered public client (RFC 7591). No secret: PKCE instead."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_name: Mapped[str] = mapped_column(String(100))
    # JSON list; validated on registration (https, or http on loopback only).
    redirect_uris: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OAuthAuthorizationCode(Base):
    """A consented, not-yet-exchanged authorization. Single use, short-lived."""

    __tablename__ = "oauth_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[str] = mapped_column(String(255))
    resource: Mapped[str] = mapped_column(String(255))
    session_version: Mapped[int] = mapped_column(Integer)
    wrapped_dek: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthGrant(Base):
    """A user's standing authorization of one client: the refresh-token family.

    The refresh token rotates on every use; the one it replaced is remembered
    so a replay (a sign of theft) revokes the whole grant. Access tokens carry
    the grant id and die with it.
    """

    __tablename__ = "oauth_grants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), index=True
    )
    scopes: Mapped[str] = mapped_column(String(255))
    resource: Mapped[str] = mapped_column(String(255))
    # The user's session_version at consent: a password change/reset bumps it
    # and so revokes every grant.
    session_version: Mapped[int] = mapped_column(Integer)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    previous_refresh_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    wrapped_dek: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Sliding idle expiry, pushed forward on every refresh.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
