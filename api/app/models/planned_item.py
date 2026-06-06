"""Planned one-off / recurring / installment expenses (and incomes).

These are user-entered future money-movements ("what if I split this?") that feed
the cashflow projection alongside detected commitments.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlannedKind(str, Enum):
    ONE_OFF = "one_off"
    RECURRING = "recurring"
    INSTALLMENT_PLAN = "installment_plan"  # split a total into N payments


class PlannedItem(Base):
    """A planned future expense or income."""

    __tablename__ = "planned_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(10), default="expense")  # income | expense
    kind: Mapped[str] = mapped_column(String(20))  # PlannedKind

    start_date: Mapped[date] = mapped_column(Date)

    # one_off / recurring: amount per occurrence.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(precision=12, scale=2), nullable=True)
    # recurring: cadence + interval.
    cadence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    interval_days: Mapped[int | None] = mapped_column(nullable=True)
    interval_months: Mapped[int | None] = mapped_column(nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # installment_plan: split total over N payments, optionally with interest/fees.
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(precision=12, scale=2), nullable=True)
    installments: Mapped[int | None] = mapped_column(nullable=True)
    apr: Mapped[Decimal | None] = mapped_column(Numeric(precision=6, scale=3), nullable=True)
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(precision=12, scale=2), nullable=True)

    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
