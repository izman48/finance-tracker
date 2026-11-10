"""Repayment marks (T-03-3; PRD T-03-1 "Model").

"This much of an incoming payment paid back something": a spend (netted in
the spend's cycle) or, with no spend, a category (netted in the cycle the
credit arrived). The amount and the label are money and bank text, so they
are DEK-encrypted; ids, category, `active` and `created_via` are plain, as
`transactions.category` is. Unmarking is a soft delete (`active` false), so
Claude's changes keep their history and undo works.

Caps can't be checked in SQL (the amounts are encrypted): writes check them
in Python under a user lock, and reads clamp (`services/repayment_marks`).
Partial unique indexes allow one active mark per credit and spend, and per
credit and category. Deleting the user or either transaction deletes the mark.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.encryption import UserEncryptedDecimal, UserEncryptedString


def _now() -> datetime:
    # Set in Python, not only by the database: reads clamp marks oldest
    # first, and marks written in one transaction share the database's now().
    return datetime.now(timezone.utc)


class RepaymentMark(Base):
    __tablename__ = "repayment_marks"
    __table_args__ = (
        CheckConstraint(
            "(spend_transaction_id IS NULL) <> (category IS NULL)", name="ck_repayment_marks_one_target",
        ),
        Index(
            "uq_repayment_marks_credit_spend_active", "credit_transaction_id", "spend_transaction_id",
            unique=True, postgresql_where=text("active"), sqlite_where=text("active"),
        ),
        Index(
            "uq_repayment_marks_credit_category_active", "credit_transaction_id", "category",
            unique=True, postgresql_where=text("active"), sqlite_where=text("active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credit_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    spend_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    # For the audit trail, e.g. "Sam £60, Pizza Express".
    label: Mapped[str] = mapped_column(UserEncryptedString)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # "mcp" (Claude) or "web": Claude may unmark only its own (T-03-2 T2).
    created_via: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
