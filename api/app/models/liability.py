"""Debts the user enters by hand: loans, retail finance, buy now pay later.

TrueLayer returns no loan data, so the user types the terms. Only the terms
are stored; payoff date, interest left and total cost are computed on read
(services/liabilities.py). Lender, balance, APR and payment are wealth data
and DEK-encrypted; kind, cadence and dates stay plaintext.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.encryption import UserEncryptedDecimal, UserEncryptedString


class LiabilityKind(str, Enum):
    # Card plans and mortgages come in later stages of the liabilities spec.
    LOAN = "loan"
    FINANCE = "finance"
    BNPL = "bnpl"


class LiabilityCadence(str, Enum):
    MONTHLY = "monthly"
    FOUR_WEEKLY = "four_weekly"
    FORTNIGHTLY = "fortnightly"
    WEEKLY = "weekly"


class Liability(Base):
    __tablename__ = "liabilities"
    __table_args__ = (
        UniqueConstraint("linked_commitment_id", name="uq_liabilities_linked_commitment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    kind: Mapped[str] = mapped_column(String(20))  # LiabilityKind
    lender: Mapped[str] = mapped_column(UserEncryptedString)

    # The balance owed on `balance_as_of`, with any payment due that day taken.
    balance: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    balance_as_of: Mapped[date] = mapped_column(Date)

    # Effective annual rate in percent, as UK lenders quote it.
    apr: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    # Null only when the user repays irregularly (`opted_out`).
    payment: Mapped[Decimal | None] = mapped_column(UserEncryptedDecimal, nullable=True)
    cadence: Mapped[str] = mapped_column(String(20), default=LiabilityCadence.MONTHLY.value)
    # The first payment; it sets the payment day.
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # The commitment that carries this liability's repayment (T-10-8). Set
    # only by the server; one liability per commitment. Deleting the
    # commitment unlinks the liability, whose balance then stays as entered.
    linked_commitment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "commitment_rules.id", ondelete="SET NULL",
            name="fk_liabilities_linked_commitment_id_commitment_rules",
        ),
        nullable=True,
    )

    # "I repay this loan irregularly": no schedule, so no payoff figures, and
    # no linked commitment.
    opted_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
