"""At most 100 holdings per user (ADR-002 section 6; sec on #203).

Every net worth, projection and graph read projects each holding month by
month, so the number is bounded at create: the 101st asset is a 409 and
nothing is written. A check-then-act bound: the engine never relies on it.
"""
from decimal import Decimal

from app.models import Asset, AssetValuation
from app.routers import assets as assets_router
from tests.clock import TODAY
from tests.integration.test_linked_commitment_guards import API, World, _bearer

BODY = {"name": "Fund", "asset_type": "investment", "value": "10"}


def _count(world):
    return world.db.query(Asset).filter(Asset.user_id == world.user.id).count()


def test_the_cap_is_100():
    assert assets_router.HOLDINGS_PER_USER_MAX == 100


def test_past_the_cap_adding_is_409_and_writes_nothing(client, db_session, monkeypatch):
    monkeypatch.setattr(assets_router, "HOLDINGS_PER_USER_MAX", 2)
    world = World(client, db_session, email="cap@example.com")
    for _ in range(2):
        assert client.post(f"{API}/assets", json=BODY, headers=_bearer(world.web)).status_code == 201
    res = client.post(f"{API}/assets", json=BODY, headers=_bearer(world.web))
    assert res.status_code == 409
    assert res.json()["detail"] == "You can track up to 2 holdings. Delete one to add another."
    assert _count(world) == 2


def test_the_cap_is_per_user(client, db_session, monkeypatch):
    monkeypatch.setattr(assets_router, "HOLDINGS_PER_USER_MAX", 1)
    alice = World(client, db_session, email="cap-alice@example.com")
    bob = World(client, db_session, email="cap-bob@example.com")
    assert client.post(f"{API}/assets", json=BODY, headers=_bearer(alice.web)).status_code == 201
    assert client.post(f"{API}/assets", json=BODY, headers=_bearer(bob.web)).status_code == 201


def test_an_existing_holding_over_the_cap_still_reads(client, db_session, monkeypatch):
    # Stored before the cap (or by a race): reads never fail on the count.
    world = World(client, db_session, email="cap-reads@example.com")
    with world.as_user():
        for n in range(3):
            asset = Asset(user_id=world.user.id, name=f"Fund {n}", asset_type="investment")
            world.db.add(asset)
            world.db.flush()
            world.db.add(AssetValuation(asset_id=asset.id, value=Decimal("10"), valued_at=TODAY))
        world.db.commit()
    monkeypatch.setattr(assets_router, "HOLDINGS_PER_USER_MAX", 2)
    assert client.get(f"{API}/assets", headers=_bearer(world.web)).status_code == 200
    assert client.get(f"{API}/analytics/summary", headers=_bearer(world.web)).status_code == 200
