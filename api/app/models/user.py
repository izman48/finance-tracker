import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    """User model - represents a person using the application."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    # TrueLayer tokens (encrypted in production)
    truelayer_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    truelayer_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    truelayer_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    accounts: Mapped[list["Account"]] = relationship(
        "Account", back_populates="user", cascade="all, delete-orphan"
    )
    bank_connections: Mapped[list["BankConnection"]] = relationship(
        "BankConnection", back_populates="user", cascade="all, delete-orphan"
    )


# Import here to avoid circular imports
from app.models.account import Account  # noqa: E402, F401
from app.models.bank_connection import BankConnection  # noqa: E402, F401
