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
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
