import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AccountType(str, Enum):
    """Types of bank accounts (matching TrueLayer's format)."""

    TRANSACTION = "TRANSACTION"  # Current/checking account
    SAVINGS = "SAVINGS"
    CREDIT_CARD = "CREDIT_CARD"
    LOAN = "LOAN"
    MORTGAGE = "MORTGAGE"
    OTHER = "OTHER"


class Account(Base):
    """Bank account model."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    bank_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="CASCADE"), index=True
    )

    # External identifiers from TrueLayer
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    provider_name: Mapped[str] = mapped_column(String(255))  # e.g., "HSBC", "Monzo"

    # Account details
    account_type: Mapped[AccountType] = mapped_column(String(50))
    display_name: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default="GBP")

    # Balance (updated periodically)
    current_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )
    available_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )
    balance_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="accounts")
    bank_connection: Mapped["BankConnection"] = relationship("BankConnection", back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )


# Import here to avoid circular imports
from app.models.user import User  # noqa: E402, F401
from app.models.bank_connection import BankConnection  # noqa: E402, F401
from app.models.transaction import Transaction  # noqa: E402, F401
