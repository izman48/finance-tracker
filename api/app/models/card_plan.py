"""Card instalment plans (T-12-5a; ADR-002 holding kind `card_plan`).

A purchase repaid in fixed monthly instalments plus a fee inside a credit
card (Amex Plan It, Monzo Flex). TrueLayer reports no plan data, so the user
types the terms. Name and amounts are wealth data and DEK-encrypted; the
card link, counts and dates stay plaintext. The card link is SET NULL when
the card goes (bank disconnect): the plan then stays as standalone debt.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.encryption import UserEncryptedDecimal, UserEncryptedString


class CardPlan(Base):
    __tablename__ = "card_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(UserEncryptedString)
    # What is left to repay as entered, before the instalment on `next_date`.
    balance: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    instalment: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    # Monthly fee charged with each instalment (£).
    fee: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    apr: Mapped[Decimal | None] = mapped_column(UserEncryptedDecimal, nullable=True)
    instalments_remaining: Mapped[int] = mapped_column(Integer)
    # The next instalment as entered; later ones fall on the same day monthly.
    next_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
