"""Bank connection model for storing multiple bank OAuth tokens per user."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.encryption import UserEncryptedString, UserEncryptedToken


class BankConnection(Base):
    """Bank connection with OAuth tokens for a specific provider."""

    __tablename__ = "bank_connections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    # Provider information — which bank a user banks with is user data, so
    # both fields are DEK-encrypted (dedupe on provider_id happens in Python).
    provider_id: Mapped[str] = mapped_column(UserEncryptedString, nullable=False)  # TrueLayer provider ID
    provider_name: Mapped[str] = mapped_column(UserEncryptedString, nullable=False)  # e.g., "Monzo", "Barclays"

    # TrueLayer OAuth tokens: DEK layer inside, server Fernet layer outside.
    # At rest they need both the server key and a user secret to read.
    access_token: Mapped[str | None] = mapped_column(UserEncryptedToken, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(UserEncryptedToken, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # When accounts/transactions were last successfully pulled from TrueLayer.
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="bank_connections")
    accounts: Mapped[list["Account"]] = relationship(
        "Account", back_populates="bank_connection", cascade="all, delete-orphan"
    )
