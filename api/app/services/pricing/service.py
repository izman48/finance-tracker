"""Request-time pricing: search, cache, and snapshot into valuations.

The snapshot is the trick that keeps the rest of the app untouched: on each
Wealth load we compute a priced asset's value (units x latest price) and write
it as an ordinary AssetValuation for today. Net worth, history, projections and
the contribution/growth split then work exactly as they do for manual assets —
they never need to know pricing exists. It also means the chart builds its own
history, one point per day you open Wealth.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Asset, AssetValuation, Instrument, InstrumentPrice

from . import providers

# Skip a provider call when the cached price is fresher than this. Lowering it
# (or moving refresh to a cron) is the whole "background job later" step.
PRICE_TTL = timedelta(hours=1)


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _get_or_create_instrument(db: Session, h) -> Instrument:
    inst = (
        db.query(Instrument)
        .filter(Instrument.provider == h.provider, Instrument.provider_ref == h.provider_ref)
        .first()
    )
    if inst is not None:
        return inst
    inst = Instrument(
        symbol=h.symbol, name=h.name, kind=h.kind, provider=h.provider,
        provider_ref=h.provider_ref, currency=h.currency,
    )
    db.add(inst)
    try:
        db.flush()
    except IntegrityError:
        # Another request inserted the same (provider, provider_ref) first —
        # roll back and use theirs (unique constraint, not a real failure).
        db.rollback()
        inst = (
            db.query(Instrument)
            .filter(Instrument.provider == h.provider, Instrument.provider_ref == h.provider_ref)
            .first()
        )
    return inst


def search_instruments(db: Session, query: str) -> list[Instrument]:
    """Search providers and upsert the hits so the UI can link by a stable id."""
    out = [_get_or_create_instrument(db, h) for h in providers.search(query)]
    out = [i for i in out if i is not None]
    db.commit()
    return out


def latest_price(db: Session, instrument_id) -> InstrumentPrice | None:
    # Most recently FETCHED row is the current price (created_at), not the one
    # with the newest provider as_of — a provider can hand back an older as_of.
    return (
        db.query(InstrumentPrice)
        .filter(InstrumentPrice.instrument_id == instrument_id)
        .order_by(InstrumentPrice.created_at.desc(), InstrumentPrice.as_of.desc())
        .first()
    )


def get_or_refresh_price(db: Session, instrument: Instrument, force: bool = False) -> InstrumentPrice | None:
    """Return the freshest price, hitting the provider only when the cache is
    stale (or forced). On a provider failure, serve the stale price if we have
    one rather than nothing.

    Freshness is keyed on WHEN WE FETCHED (created_at), never the provider's
    own as_of — a lagging or future provider timestamp must not defeat the
    cache (perpetual refetch) or freeze the price (perpetual hit).
    """
    last = latest_price(db, instrument.id)
    now = datetime.now(timezone.utc)
    if last is not None and not force:
        age = (now - (_aware(last.created_at) or now)).total_seconds()
        if 0 <= age < PRICE_TTL.total_seconds():
            return last
    q = providers.quote(instrument.provider, instrument.provider_ref, instrument.currency)
    if q is None:
        return last
    row = InstrumentPrice(
        instrument_id=instrument.id, price_gbp=q.price_gbp, price_native=q.price_native,
        as_of=_aware(q.as_of) or now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _today() -> date:
    return datetime.now(timezone.utc).date()


def price_and_snapshot(db: Session, user) -> int:
    """Refresh every priced asset and write today's value as a valuation.

    Requires the user's DEK in session (valuations are encrypted) — call it
    from an authenticated request, never a background job. Returns how many
    assets were repriced.
    """
    assets = (
        db.query(Asset)
        .filter(Asset.user_id == user.id, Asset.instrument_id.isnot(None))
        .all()
    )
    today = _today()
    n = 0
    for a in assets:
        if a.units is None or a.instrument is None:
            continue
        price = get_or_refresh_price(db, a.instrument)
        if price is None:
            continue
        value = (_d(a.units) * _d(price.price_gbp)).quantize(Decimal("0.01"))
        existing = (
            db.query(AssetValuation)
            .filter(AssetValuation.asset_id == a.id, AssetValuation.valued_at == today)
            .first()
        )
        if existing is not None:
            existing.value = value
        else:
            db.add(AssetValuation(asset_id=a.id, value=value, valued_at=today))
        n += 1
    db.commit()
    return n
