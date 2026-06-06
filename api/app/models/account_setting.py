"""Per-account user configuration (role, overdraft, credit-card repayment).

Kept in a separate table from `accounts` so that re-syncing balances from
TrueLayer never clobbers the user's settings. One row per account.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AccountRole(str, Enum):
    """How an account participates in the cashflow model."""

    SPENDING = "spending"   # current accounts — counted in safe-to-spend
    SAVINGS = "savings"     # liquid but earmarked — shown separately
    CREDIT = "credit"       # credit cards — owed, repaid on a schedule
    EXCLUDED = "excluded"   # ignored entirely


class RepaymentCadence(str, Enum):
    """How often a credit account is repaid."""

    MONTHLY = "monthly"             # on repayment_day each month
    END_OF_MONTH = "end_of_month"   # last day of each month (e.g. Amex)
    EVERY_N_MONTHS = "every_n_months"  # every repayment_interval_months (e.g. Flex)
    WEEKLY = "weekly"


class RepaymentStrategy(str, Enum):
    """How much is paid on each repayment date."""

    FULL_BALANCE = "full_balance"      # whole outstanding balance each cycle (e.g. Amex)
    FIXED = "fixed"                    # repayment_fixed_amount each time
    INSTALLMENTS = "installments"      # split the balance over N payments (e.g. Monzo Flex)
    MINIMUM_PERCENT = "minimum_percent"  # a percentage of the balance


class AccountSetting(Base):
    """User-configured settings for a single account."""

    __tablename__ = "account_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Role in the cashflow model (defaulted from account_type on first creation)
    role: Mapped[AccountRole] = mapped_column(String(20), default=AccountRole.EXCLUDED)

    # For spending accounts: agreed overdraft limit (positive number = how far
    # below zero the balance may go). Shown as a separate cushion, not in safe-to-spend.
    overdraft_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )

    # For credit accounts: when/how the balance is repaid from a spending account.
    repayment_cadence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    repayment_interval_months: Mapped[int | None] = mapped_column(nullable=True)
    repayment_day: Mapped[int | None] = mapped_column(nullable=True)
    repayment_anchor_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    repayment_strategy: Mapped[str] = mapped_column(
        String(20), default=RepaymentStrategy.FULL_BALANCE.value
    )
    repayment_fixed_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )
    # For the `installments` strategy: number of payments to clear the balance.
    repayment_installments: Mapped[int | None] = mapped_column(nullable=True)
    pay_from_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationship to the owning account (one-to-one). foreign_keys is explicit
    # because the table has two FKs to accounts (account_id + pay_from_account_id).
    account: Mapped["Account"] = relationship(
        "Account", foreign_keys=[account_id]
    )
