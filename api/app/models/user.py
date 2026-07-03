import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    """User model - represents a person using the application."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    # Per-user envelope encryption (core/user_crypto.py). The DEK is stored
    # only in wrapped form: once under the password-derived KEK, once under
    # the recovery-code KEK. The server never persists either secret, so
    # these columns are useless to an operator. Nullable only for accounts
    # created before this feature — provisioned at their next login.
    wrapped_dek: Mapped[str | None] = mapped_column(Text, nullable=True)
    dek_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recovery_wrapped_dek: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovery_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Bank OAuth tokens live on BankConnection (one row per connected bank),
    # stored encrypted at rest. The legacy single-token columns were removed.

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
