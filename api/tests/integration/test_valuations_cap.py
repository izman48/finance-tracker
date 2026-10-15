"""At most 1,000 values per holding (T-12-8; sec on #223 and #209).

`graphs._total_history` walks every valuation for every point, so the count
per asset is bounded where values are added: a new date past the cap is a
409 and nothing is written. Correcting a date that already has a value is
an overwrite, so it is still allowed at the cap. Reads never fail on the
count. Synthetic figures.
"""
import uuid
from datetime import timedelta

from app.models import AssetValuation
from app.routers import assets as assets_router
from tests.clock import TODAY
from tests.integration.test_linked_commitment_guards import API, World, _bearer


def _asset(world):
    res = world.client.post(f"{API}/assets", json={"name": "Fund", "asset_type": "investment", "value": "10"},
                            headers=_bearer(world.web))
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _value(world, asset_id, days_ago, value="20"):
    return world.client.post(f"{API}/assets/{asset_id}/valuations",
                             json={"value": value, "valued_at": (TODAY - timedelta(days=days_ago)).isoformat()},
                             headers=_bearer(world.web))


def _count(world, asset_id):
    return world.db.query(AssetValuation).filter(AssetValuation.asset_id == uuid.UUID(asset_id)).count()


def test_the_cap_is_1000():
    assert assets_router.VALUATIONS_PER_ASSET_MAX == 1000


def test_a_new_date_past_the_cap_is_409_and_writes_nothing(client, db_session, monkeypatch):
    monkeypatch.setattr(assets_router, "VALUATIONS_PER_ASSET_MAX", 3)
    world = World(client, db_session, email="val-cap@example.com")
    asset_id = _asset(world)  # its first value, today
    assert [_value(world, asset_id, d).status_code for d in (1, 2)] == [201, 201]
    res = _value(world, asset_id, 3)
    assert res.status_code == 409
    assert res.json()["detail"] == "This holding has 3 values already. Delete an old one to add another."
    assert _count(world, asset_id) == 3


def test_at_the_cap_a_dates_value_can_still_be_corrected(client, db_session, monkeypatch):
    monkeypatch.setattr(assets_router, "VALUATIONS_PER_ASSET_MAX", 2)
    world = World(client, db_session, email="val-cap-fix@example.com")
    asset_id = _asset(world)
    assert _value(world, asset_id, 1).status_code == 201
    res = _value(world, asset_id, 1, value="25")
    assert res.status_code == 201, res.text
    assert _count(world, asset_id) == 2


def test_the_cap_is_per_asset(client, db_session, monkeypatch):
    monkeypatch.setattr(assets_router, "VALUATIONS_PER_ASSET_MAX", 1)
    world = World(client, db_session, email="val-cap-each@example.com")
    first, second = _asset(world), _asset(world)
    assert _value(world, first, 1).status_code == 409
    assert _value(world, second, 0, value="30").status_code == 201  # today: an overwrite
    assert client.get(f"{API}/assets", headers=_bearer(world.web)).status_code == 200
