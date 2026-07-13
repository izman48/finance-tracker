"""Manually tracked assets (ISAs, pensions, property, …).

Open Banking only covers current accounts and cards; everything else the user
tells us about. Each value update appends an AssetValuation, so net worth can
be reconstructed at any point in time.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.encryption import UserEncryptedDecimal, UserEncryptedString

ASSET_TYPES = (
    "isa", "savings", "investment", "pension", "property", "crypto", "other",
    # Liabilities — stored with a negative valuation (amount owed).
    "mortgage", "loan", "other_liability",
)
LIABILITY_TYPES = ("mortgage", "loan", "other_liability")


class Asset(Base):
    """A manually valued asset belonging to a user."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # What the user owns and what it's worth is wealth data — DEK-encrypted.
    name: Mapped[str] = mapped_column(UserEncryptedString)
    asset_type: Mapped[str] = mapped_column(String(20), default="other")

    # Projection assumption: annual %/yr this asset is assumed to grow (may be
    # negative). Null → the projection's global growth rate for assets, 0 for
    # liabilities. A typed assumption, not wealth data — plaintext.
    assumed_growth_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    # Planned monthly saving into this asset (e.g. an ISA direct debit). The
    # projection adds it to the asset each month; the cash side is already in
    # measured spending, so declaring it here moves the money from "consumption"
    # to "wealth". Positive on a liability = paydown. Describes the user's
    # saving behaviour — DEK-encrypted like valuation amounts.
    monthly_contribution: Mapped[Decimal | None] = mapped_column(
        UserEncryptedDecimal, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    valuations: Mapped[list["AssetValuation"]] = relationship(
        "AssetValuation",
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="AssetValuation.valued_at",
    )
    flows: Mapped[list["AssetFlow"]] = relationship(
        "AssetFlow",
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="AssetFlow.flow_date",
    )


class AssetValuation(Base):
    """The asset's value as of a date (negative allowed, e.g. a loan)."""

    __tablename__ = "asset_valuations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )

    value: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    valued_at: Mapped[date] = mapped_column(Date, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    asset: Mapped["Asset"] = relationship("Asset", back_populates="valuations")


class AssetFlow(Base):
    """A recorded deposit into (+) or withdrawal from (−) an asset.

    Valuations alone can't tell saving from market movement; flows are what
    lets the decomposition say "£8k up — £5k added, £3k growth". Growth in a
    window = Δvaluation − Σflows.
    """

    __tablename__ = "asset_flows"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )

    # Signed: positive = money in, negative = money out. Wealth data — encrypted.
    amount: Mapped[Decimal] = mapped_column(UserEncryptedDecimal)
    flow_date: Mapped[date] = mapped_column(Date, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    asset: Mapped["Asset"] = relationship("Asset", back_populates="flows")
