"""User-defined auto-categorization rules.

Created implicitly: when a user categorizes a transaction, the merchant →
category mapping is remembered and applied to that merchant's other and
future transactions.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def merchant_match_key(merchant_name: str | None, description: str | None) -> str | None:
    """Normalized key a transaction is matched on (merchant, else description)."""
    raw = (merchant_name or description or "").strip().lower()
    return raw or None


class CategoryRule(Base):
    """Maps a normalized merchant key to a category for one user."""

    __tablename__ = "category_rules"
    __table_args__ = (UniqueConstraint("user_id", "match_key", name="uq_category_rule_user_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    match_key: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
