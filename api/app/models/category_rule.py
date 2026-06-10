"""User-defined auto-categorization rules, organized into shareable packs.

Rules are created three ways: learned implicitly when a user categorizes a
transaction, written manually on the Rules page, or imported (copied) from
another user's shared pack.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def merchant_match_key(merchant_name: str | None, description: str | None) -> str | None:
    """Normalized key a transaction is matched on (merchant, else description)."""
    raw = (merchant_name or description or "").strip().lower()
    return raw or None


class RulePack(Base):
    """A named, shareable collection of categorization rules."""

    __tablename__ = "rule_packs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Set when the owner shares the pack; the import URL is /r/<share_code>.
    share_code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    # Provenance note for imported packs, e.g. "Imported from 'UK Essentials'".
    imported_from: Mapped[str | None] = mapped_column(String(150), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    rules: Mapped[list["CategoryRule"]] = relationship(
        "CategoryRule", back_populates="pack", cascade="all, delete-orphan"
    )


class CategoryRule(Base):
    """Maps a transaction pattern to a category for one user."""

    __tablename__ = "category_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rule_packs.id", ondelete="CASCADE"), nullable=True, index=True
    )

    pattern: Mapped[str] = mapped_column(String(255))
    # exact | contains | regex
    match_type: Mapped[str] = mapped_column(String(10), default="exact")
    # any | merchant | description
    match_field: Mapped[str] = mapped_column(String(12), default="any")
    category: Mapped[str] = mapped_column(String(100))
    # learned | manual | imported
    source: Mapped[str] = mapped_column(String(10), default="learned")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pack: Mapped["RulePack | None"] = relationship("RulePack", back_populates="rules")
