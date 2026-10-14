"""A credit card's statement: what was billed, when it closed, when it is due.

Entered by the user (`manual`) or, later, read from the provider's card
balance response (`provider`). One row per card per statement date per
source; a manual row wins over a provider row for the same date. Money is
encrypted with the user's key; only ids, dates and the source are plaintext,
so the unique constraint uses plaintext columns only.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.encryption import UserEncryptedDecimal


class StatementSource(str, Enum):
    MANUAL = "manual"
    PROVIDER = "provider"


class CardStatement(Base):
    __tablename__ = "card_statements"
    __table_args__ = (
        UniqueConstraint("account_id", "statement_date", "source", name="uq_card_statements_period_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )

    statement_date: Mapped[date] = mapped_column(Date)  # the day the statement closed
    due_date: Mapped[date] = mapped_column(Date)
    statement_balance: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    minimum_due: Mapped[Decimal | None] = mapped_column(UserEncryptedDecimal, nullable=True)
    source: Mapped[str] = mapped_column(String(10), default=StatementSource.MANUAL.value)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
