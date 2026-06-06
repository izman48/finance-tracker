"""Savings goals — fund toward a target.

Savings stays passive: a goal tracks progress toward a target amount and (with a
target date) how much you'd need to set aside each month. Progress can either be
read from a linked savings account's balance, or tracked manually. No automatic
money movement.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SavingsGoal(Base):
    """A savings target for a user."""

    __tablename__ = "savings_goals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(255))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(precision=12, scale=2))
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Progress source: a linked savings account's balance, or a manual amount.
    linked_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    current_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0")
    )

    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
