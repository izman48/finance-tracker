"""Investment / ISA holdings — manually-maintained external balances.

InvestEngine (and most ISA providers) have no public balance API, so the value
is entered by the user. We keep the provider's share/portfolio URL for quick
access and an "as of" timestamp so it's clear how fresh the figure is. Designed
so an automatic balance sync could later replace the manual value with minimal
change.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InvestmentHolding(Base):
    """An external investment account (e.g. a Stocks & Shares ISA)."""

    __tablename__ = "investment_holdings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(255))           # e.g. "InvestEngine ISA"
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_value: Mapped[Decimal] = mapped_column(Numeric(precision=12, scale=2), default=Decimal("0"))
    external_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Updated whenever the value is edited — surfaced as the "as of" date.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
