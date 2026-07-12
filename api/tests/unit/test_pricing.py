"""Pricing service: caching, GBP normalisation, and the valuation snapshot.

Providers are stubbed — no network. The snapshot is the load-bearing bit: a
priced asset must turn into ordinary valuations so the rest of the app keeps
working, and the cache must not hammer the provider.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import Asset, AssetValuation, Instrument, User
from app.services.pricing import providers, service


def _user(db):
    u = User(email=f"px-{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _instrument(db, provider="coingecko", ref="bitcoin", currency="GBP", symbol="BTC"):
    inst = Instrument(symbol=symbol, name=symbol, kind="crypto", provider=provider, provider_ref=ref, currency=currency)
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _quote(gbp, native=None, as_of=None):
    return providers.Quote(
        price_native=Decimal(str(native if native is not None else gbp)),
        price_gbp=Decimal(str(gbp)),
        as_of=as_of or datetime.now(timezone.utc),
    )


class TestPriceCache:
    def test_fresh_cache_skips_the_provider(self, db_session, monkeypatch):
        inst = _instrument(db_session)
        calls = {"n": 0}

        def fake_quote(provider, ref, currency):
            calls["n"] += 1
            return _quote("50000")

        monkeypatch.setattr(providers, "quote", fake_quote)
        p1 = service.get_or_refresh_price(db_session, inst)
        p2 = service.get_or_refresh_price(db_session, inst)  # within TTL
        assert p1.price_gbp == Decimal("50000")
        assert p2.id == p1.id
        assert calls["n"] == 1  # cache hit, no second call

    def test_lagging_provider_timestamp_still_caches(self, db_session, monkeypatch):
        """Freshness keys on our fetch time, not the provider's as_of — a coin
        whose as_of lags the TTL must still hit the cache, not refetch forever."""
        inst = _instrument(db_session)
        calls = {"n": 0}

        def fake_quote(*a):
            calls["n"] += 1
            return _quote("100", as_of=datetime.now(timezone.utc) - timedelta(hours=3))

        monkeypatch.setattr(providers, "quote", fake_quote)
        service.get_or_refresh_price(db_session, inst)
        service.get_or_refresh_price(db_session, inst)  # created_at is fresh
        assert calls["n"] == 1

    def test_stale_cache_refetches(self, db_session, monkeypatch):
        inst = _instrument(db_session)
        prices = iter([_quote("100"), _quote("200")])
        monkeypatch.setattr(providers, "quote", lambda *a: next(prices))
        first = service.get_or_refresh_price(db_session, inst)
        # Age the cached row's FETCH time past the TTL.
        first.created_at = datetime.now(timezone.utc) - service.PRICE_TTL - timedelta(minutes=1)
        db_session.commit()
        second = service.get_or_refresh_price(db_session, inst)
        assert second.price_gbp == Decimal("200")

    def test_provider_failure_serves_stale_not_nothing(self, db_session, monkeypatch):
        inst = _instrument(db_session)
        monkeypatch.setattr(providers, "quote", lambda *a: _quote("100"))
        good = service.get_or_refresh_price(db_session, inst)
        good.created_at = datetime.now(timezone.utc) - service.PRICE_TTL - timedelta(minutes=1)
        db_session.commit()
        monkeypatch.setattr(providers, "quote", lambda *a: None)  # network down
        served = service.get_or_refresh_price(db_session, inst)
        assert served.price_gbp == Decimal("100")  # last good price


class TestSnapshot:
    def test_priced_asset_becomes_a_valuation(self, db_session, monkeypatch):
        user = _user(db_session)
        inst = _instrument(db_session)
        asset = Asset(user_id=user.id, name="BTC", asset_type="crypto", instrument_id=inst.id, units=Decimal("0.5"))
        db_session.add(asset)
        db_session.commit()
        monkeypatch.setattr(providers, "quote", lambda *a: _quote("40000"))

        n = service.price_and_snapshot(db_session, user)
        assert n == 1
        today = service._today()
        val = (
            db_session.query(AssetValuation)
            .filter(AssetValuation.asset_id == asset.id, AssetValuation.valued_at == today)
            .first()
        )
        assert val is not None and val.value == Decimal("20000.00")  # 0.5 x 40000

    def test_second_snapshot_same_day_overwrites(self, db_session, monkeypatch):
        user = _user(db_session)
        inst = _instrument(db_session)
        asset = Asset(user_id=user.id, name="BTC", asset_type="crypto", instrument_id=inst.id, units=Decimal("1"))
        db_session.add(asset)
        db_session.commit()
        prices = iter([_quote("40000"), _quote("41000")])
        monkeypatch.setattr(providers, "quote", lambda *a: next(prices))

        service.price_and_snapshot(db_session, user)
        # Force a refetch by ageing the cache (fetch time), then snapshot again.
        db_session.query(service.InstrumentPrice).update(
            {"created_at": datetime.now(timezone.utc) - service.PRICE_TTL - timedelta(minutes=1)}
        )
        db_session.commit()
        service.price_and_snapshot(db_session, user)

        vals = (
            db_session.query(AssetValuation)
            .filter(AssetValuation.asset_id == asset.id, AssetValuation.valued_at == service._today())
            .all()
        )
        assert len(vals) == 1 and vals[0].value == Decimal("41000.00")

    def test_unlinked_or_unitless_assets_are_skipped(self, db_session, monkeypatch):
        user = _user(db_session)
        inst = _instrument(db_session)
        # linked but no units → skipped
        db_session.add(Asset(user_id=user.id, name="A", asset_type="crypto", instrument_id=inst.id, units=None))
        # not linked → skipped
        db_session.add(Asset(user_id=user.id, name="B", asset_type="isa"))
        db_session.commit()
        monkeypatch.setattr(providers, "quote", lambda *a: _quote("100"))
        assert service.price_and_snapshot(db_session, user) == 0


class TestSearchUpsert:
    def test_search_upserts_and_dedupes(self, db_session, monkeypatch):
        hit = providers.InstrumentHit(symbol="BTC", name="Bitcoin", kind="crypto", provider="coingecko", provider_ref="bitcoin", currency="GBP")
        monkeypatch.setattr(providers, "search", lambda q: [hit])
        first = service.search_instruments(db_session, "bit")
        second = service.search_instruments(db_session, "bit")  # same hit again
        assert len(first) == 1 and first[0].symbol == "BTC"
        assert second[0].id == first[0].id  # not duplicated
        assert db_session.query(Instrument).count() == 1


class TestFxNormalisation:
    @pytest.mark.parametrize("cur,factor", [("GBP", "1"), ("GBX", "0.01"), ("PENCE", "0.01")])
    def test_pence_and_gbp_need_no_network(self, cur, factor):
        assert providers._fx_to_gbp(cur) == Decimal(factor)
