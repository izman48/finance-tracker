"""Priceable instruments and their public price history.

The encryption line runs right through holdings: **prices are public**, so
instruments and their prices are plaintext tables a scheduler can refresh
without any user's key. **Units are the user's** and stay encrypted on the
Asset. A live valuation = units (decrypted in-session) x latest plaintext
price, computed request-time.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Instrument(Base):
    """A priceable security or coin — public reference data, not user data."""

    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("provider", "provider_ref", name="uq_instrument_provider_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), index=True)   # BTC, VUSA.LON, AAPL
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))                 # crypto | equity | etf
    provider: Mapped[str] = mapped_column(String(20))            # coingecko | alphavantage
    provider_ref: Mapped[str] = mapped_column(String(64))        # the provider's own id
    # Currency the provider quotes in (USD, GBP, GBX=pence). We normalise to GBP.
    currency: Mapped[str] = mapped_column(String(4), default="GBP")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    prices: Mapped[list["InstrumentPrice"]] = relationship(
        "InstrumentPrice", back_populates="instrument",
        cascade="all, delete-orphan", order_by="InstrumentPrice.as_of",
    )


class InstrumentPrice(Base):
    """A cached price point (normalised to GBP), append-only. Latest = max as_of.

    Public data: a background job can write these without a session key. For
    now they're written request-time and this table doubles as the price cache
    (skip a provider call when the latest row is fresh enough).
    """

    __tablename__ = "instrument_prices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    price_gbp: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    price_native: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    instrument: Mapped["Instrument"] = relationship("Instrument", back_populates="prices")
