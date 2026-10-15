"""A mortgage's property and the house equity line (T-12-6b; ux T-12-1 B7;
sec T-12-6).

A mortgage may name one of the user's property assets
(`property_asset_id`, a plaintext FK, ON DELETE SET NULL). The property's row
in the assets list then carries `mortgage_owed` and `equity` = value today −
the mortgages' balance today (the same figures net worth uses), computed by
the API. Two mortgages on one property: value minus their sum. Equity can be
negative. It is display only: net worth, Total owed and every key figure are
unchanged by choosing a property. Only a mortgage takes a property; another
user's asset is a 404 and a non-property asset is a 422, with nothing
written. Synthetic: Sample House £250,000, Sample Bank mortgage £120,000.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models import Liability
from tests.integration.test_linked_commitment_guards import API, World, _bearer
from tests.integration.test_mortgage import MORTGAGE


@pytest.fixture
def world(client, db_session):
    return World(client, db_session, email="equity@example.com")


def _asset(world, name="Sample House", asset_type="property", value="250000"):
    res = world.client.post(f"{API}/assets", json={"name": name, "asset_type": asset_type, "value": value},
                            headers=_bearer(world.web))
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _mortgage(world, **over):
    return world.client.post(f"{API}/liabilities", json={**MORTGAGE, **over}, headers=_bearer(world.web))


def _row(world, asset_id):
    rows = world.client.get(f"{API}/assets", headers=_bearer(world.web)).json()
    return next(r for r in rows if r["id"] == asset_id)


def _figures(world):
    s = world.summary()
    return {k: Decimal(str(s[k])) for k in ("net_worth", "total_owed", "liabilities_total", "assets_total")}


def test_a_mortgage_on_a_property_shows_its_equity(world):
    house = _asset(world)
    res = _mortgage(world, property_asset_id=house)
    assert res.status_code == 201, res.text
    assert res.json()["property_asset_id"] == house
    row = _row(world, house)
    assert (Decimal(row["mortgage_owed"]), Decimal(row["equity"])) == (Decimal("120000.00"), Decimal("130000.00"))


def test_equity_can_be_negative(world):
    house = _asset(world)
    assert _mortgage(world, property_asset_id=house, balance="255000.00", payment="1600.00").status_code == 201
    assert Decimal(_row(world, house)["equity"]) == Decimal("-5000.00")


def test_two_mortgages_on_one_property_take_their_sum(world):
    house = _asset(world)
    assert _mortgage(world, property_asset_id=house).status_code == 201
    assert _mortgage(world, property_asset_id=house, lender="Second Lender", balance="20000.00",
                     payment="200.00").status_code == 201
    row = _row(world, house)
    assert (Decimal(row["mortgage_owed"]), Decimal(row["equity"])) == (Decimal("140000.00"), Decimal("110000.00"))


def test_no_mortgage_or_no_property_means_no_equity_anywhere(world):
    house = _asset(world)
    assert _mortgage(world).status_code == 201  # no property chosen
    rows = world.client.get(f"{API}/assets", headers=_bearer(world.web)).json()
    assert all(r["equity"] is None and r["mortgage_owed"] is None for r in rows)
    assert _row(world, house)["equity"] is None


def test_choosing_a_property_never_moves_net_worth_or_total_owed(world):
    house = _asset(world)
    liability_id = _mortgage(world).json()["id"]
    before = _figures(world)
    res = world.client.patch(f"{API}/liabilities/{liability_id}", json={"property_asset_id": house},
                             headers=_bearer(world.web))
    assert res.status_code == 200, res.text
    assert _figures(world) == before
    res = world.client.patch(f"{API}/liabilities/{liability_id}", json={"property_asset_id": None},
                             headers=_bearer(world.web))
    assert (res.status_code, res.json()["property_asset_id"]) == (200, None)
    assert _figures(world) == before


def test_another_users_property_is_404_and_nothing_is_written(world, client, db_session):
    bob = World(client, db_session, email="equity-bob@example.com")
    theirs = _asset(bob)
    for property_id in (theirs, "00000000-0000-0000-0000-0000000000aa"):
        res = _mortgage(world, property_asset_id=property_id)
        assert res.status_code == 404
    assert db_session.query(Liability).count() == 0


def test_only_a_property_asset_can_be_chosen(world, db_session):
    isa = _asset(world, name="Sample ISA", asset_type="isa", value="1000")
    assert _mortgage(world, property_asset_id=isa).status_code == 422
    assert db_session.query(Liability).count() == 0


def test_only_a_mortgage_takes_a_property(world, db_session):
    house = _asset(world)
    res = world.client.post(f"{API}/liabilities", json={**MORTGAGE, "kind": "loan", "balance": "9000.00",
                                                         "payment": "200.00", "property_asset_id": house},
                            headers=_bearer(world.web))
    assert res.status_code == 422
    assert db_session.query(Liability).count() == 0


def test_deleting_the_property_with_foreign_keys_on_keeps_the_mortgage(world, db_session):
    house = _asset(world)
    liability_id = _mortgage(world, property_asset_id=house).json()["id"]
    before = _figures(world)
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    try:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        db_session.execute(text("DELETE FROM asset_valuations WHERE asset_id = :a"), {"a": uuid.UUID(house).hex})
        db_session.execute(text("DELETE FROM assets WHERE id = :a"), {"a": uuid.UUID(house).hex})
        db_session.commit()
        row = world.client.get(f"{API}/liabilities/{liability_id}", headers=_bearer(world.web)).json()
        assert (row["property_asset_id"], row["linked_commitment"] is not None) == (None, True)
        assert db_session.execute(text("SELECT count(*) FROM commitment_links")).scalar() == 1
        # Only the house's £250,000 leaves; the mortgage still counts.
        assert before["net_worth"] - _figures(world)["net_worth"] == Decimal("250000.00")
    finally:
        db_session.rollback()
        db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")
