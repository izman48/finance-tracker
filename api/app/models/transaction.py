import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.encryption import UserEncryptedDecimal, UserEncryptedString


class TransactionType(str, Enum):
    """Type of transaction."""

    CREDIT = "credit"  # Money in
    DEBIT = "debit"  # Money out


class Transaction(Base):
    """Financial transaction model."""

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )

    # External identifier from TrueLayer
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    # Transaction details
    transaction_type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType, values_callable=lambda obj: [e.value for e in obj])
    )
    # Amount, description and merchant are encrypted with the user's DEK —
    # SQL never filters or aggregates on them; analytics loads rows and
    # computes in Python.
    amount: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")

    # Description and categorization
    description: Mapped[str] = mapped_column(UserEncryptedString)
    merchant_name: Mapped[str | None] = mapped_column(UserEncryptedString, nullable=True)

    # Our categorization (will be populated by categorization engine)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # True once the user hand-picked this transaction's category — rules
    # (including imported packs) never overwrite a locked category.
    category_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Recurring payment detection
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    recurring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, index=True
    )

    # Timestamps
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    account: Mapped["Account"] = relationship("Account", back_populates="transactions")

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_transactions_account_date", "account_id", "transaction_date"),
        Index("ix_transactions_category_date", "category", "transaction_date"),
    )


from app.models.account import Account  # noqa: E402, F401
