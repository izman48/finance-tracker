"""User-scheduled credit-card repayments — specific amounts on specific dates.

For the `scheduled` repayment strategy: instead of deriving payments from a
formula, the user lists exactly what they intend to pay and when (e.g. £2,000 on
30 Jun, £900 on 31 Jul). These drive the forecast directly. Kept in their own
table (one row per payment) so editing the plan never touches synced balances.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RepaymentScheduleItem(Base):
    """A single scheduled repayment for a credit account."""

    __tablename__ = "repayment_schedule_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )

    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=12, scale=2))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
