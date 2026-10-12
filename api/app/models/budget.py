"""Budgets (T-09-2; budgets concept sections 2 and 15.1).

One whole-pound limit for one of the user's categories, per pay cycle. The
limit is money, so it is DEK-encrypted like every other money field (which
also puts this table in the key-loss purge). The category is plain text
(transaction categories are), untrusted: it is validated against the user's
own categories when written and rendered as text. A removed budget is kept,
inactive, so History can still name it. At most one active budget per
category: a partial unique index enforces it, so two requests at once can't
both create one.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.encryption import UserEncryptedDecimal

CREATED_VIA_WEB, CREATED_VIA_MCP = "web", "mcp"


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        Index(
            "uq_budgets_user_category_active", "user_id", "category", unique=True,
            postgresql_where=text("active"), sqlite_where=text("active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(100))
    limit_pounds: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_via: Mapped[str] = mapped_column(String(10), default=CREATED_VIA_WEB)
    # Set when the budget is paused or removed: the remaining limit then. For
    # the rest of that cycle the category counts at max(this, spend at pace),
    # so pausing or removing never raises the budget figures (sec, T-09-4).
    # Cleared on resume. Money, so encrypted.
    held_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    held_remaining: Mapped[Decimal | None] = mapped_column(UserEncryptedDecimal, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BudgetNudge(Base):
    """An in-app budget nudge (T-09-4b): at most one per budget, cycle and
    kind (`at_limit` or `pace`), so each fires once per cycle; dismissed
    from the app only. Holds no figures: the text is built when shown."""

    __tablename__ = "budget_nudges"
    __table_args__ = (UniqueConstraint("budget_id", "cycle_start", "kind", name="uq_budget_nudges_once"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    budget_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"), index=True)
    cycle_start: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(10))
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BudgetChange(Base):
    """Append-only: a budget's limit and state from `effective_at` on
    (T-09-3). One row per change, written with the change itself, so a
    cycle's snapshot can use the limit in force at its close, never today's
    (sec: a limit changed after a cycle closed must not rewrite whether it
    was kept). Never updated or deleted, except by the key-loss purge."""

    __tablename__ = "budget_changes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    budget_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"), index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    limit_pounds: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    paused: Mapped[bool] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean)


class BudgetCycleSnapshot(Base):
    """A closed cycle's result for one budget (T-09-3), written once, the
    first time that cycle is loaded, with the user's key (spend comes from
    encrypted transactions, so no background job can). Stores the cycle's
    own dates, so a later payday change doesn't move history. Immutable:
    no route updates it. A unique (budget, cycle start) means two workers
    loading at once write one row."""

    __tablename__ = "budget_cycle_snapshots"
    __table_args__ = (UniqueConstraint("budget_id", "cycle_start", name="uq_budget_snapshots_cycle"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    budget_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"), index=True)
    cycle_start: Mapped[date] = mapped_column(Date)
    cycle_end: Mapped[date] = mapped_column(Date)
    limit_pounds: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)  # in force at close
    spent: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    paused: Mapped[bool] = mapped_column(Boolean)                        # at close
    written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
