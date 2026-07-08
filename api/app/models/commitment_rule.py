"""Recurring income / expense commitments that drive the cashflow projection.

Commitments are auto-detected from transaction history (status `suggested`) and
then confirmed or dismissed once by the user. Only `confirmed` rules count
toward safe-to-spend and the forecast. The user can also add `manual` rules.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import UserEncryptedDecimal, UserEncryptedString


class CommitmentDirection(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"


class CommitmentCadence(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    EVERY_N_MONTHS = "every_n_months"
    CUSTOM_DAYS = "custom_days"


class CommitmentSource(str, Enum):
    DETECTED = "detected"
    MANUAL = "manual"


class CommitmentStatus(str, Enum):
    SUGGESTED = "suggested"    # auto-detected, awaiting user review
    CONFIRMED = "confirmed"    # user accepted — counts in the model
    DISMISSED = "dismissed"    # user rejected — kept so we don't re-suggest


from app.core.database import Base


class CommitmentRule(Base):
    """A recurring inflow or outflow used by the cashflow engine."""

    __tablename__ = "commitment_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    direction: Mapped[str] = mapped_column(String(10))  # CommitmentDirection
    # Labels are merchant names and amounts are spending data — DEK-encrypted
    # like the transactions they derive from.
    label: Mapped[str] = mapped_column(UserEncryptedString)
    amount: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)

    cadence: Mapped[str] = mapped_column(String(20))  # CommitmentCadence
    interval_days: Mapped[int | None] = mapped_column(nullable=True)   # for custom_days
    interval_months: Mapped[int | None] = mapped_column(nullable=True)  # for every_n_months
    next_date: Mapped[date] = mapped_column(Date)

    source: Mapped[str] = mapped_column(String(10), default=CommitmentSource.DETECTED.value)
    status: Mapped[str] = mapped_column(String(10), default=CommitmentStatus.SUGGESTED.value)

    # User-designated "this is my payday": with multiple income streams, the
    # nearest credit isn't necessarily payday. When any income is flagged, the
    # payday calc (safe-to-spend, forecast, the since-payday window) uses only
    # the flagged ones; otherwise it falls back to all confirmed income. Not
    # sensitive, so a plain queryable column (unlike label/amount).
    is_payday: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Stable key derived from merchant/description, used to dedupe re-detection so a
    # dismissed/confirmed commitment is never re-suggested. Encrypted (it embeds the
    # merchant), so matching happens in Python over the user's rules, never in SQL.
    match_key: Mapped[str | None] = mapped_column(UserEncryptedString, nullable=True)

    # Which account this hits (optional; defaults handled in the projection).
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
