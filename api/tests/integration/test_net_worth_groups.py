"""Net worth history in groups (T-11-6; ux T-11-2 A1, N-1 to N-7).

Each history point carries Cash, Investments, Property and Debt, which add up
to its net worth: net_worth = cash + property - debt (+ investments when
they are included). Groups come from the kind registry: investments are owner
D1's kinds; manual savings count as Cash; property, other and unknown asset
types are Property (nothing is dropped); debt is cards owed, liabilities and
legacy asset debts. With include_investments=false the Investments figure is
still returned (the row says "Not included") but left out of net worth, and
no other group moves (sec plan note: hiding never changes a total; debt is
always a visible group). Synthetic figures only.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import AccountSetting, Asset, AssetValuation
from tests.clock import TODAY
from tests.integration.test_include_investments_api import World
from tests.integration.test_transactions_endpoint import _account

API = "/api/v1"
GROUPS = ("cash", "investments", "property", "debt")


@pytest.fixture
def world(client, db_session):
    w = World(client, db_session, email="groups@example.com")
    w.everything()  # ISA 0, pension 5,000, house 200,000, saver 3,000, old loan -1,500, bank 2,500, loan 4,000
    w.asset("Test Boat", "other", "1000", days_ago=5)

    def card():
        acc = _account(w.db, w.user.id, atype="CREDIT_CARD", name="Card", balance="700")
        w.db.add(AccountSetting(user_id=w.user.id, account_id=acc.id, role="credit"))
        w.db.commit()
    w.as_user(card)
    return w


def _history(world, **params):
    r = world.client.get(f"{API}/analytics/net-worth-history", params=params, headers=world.h)
    assert r.status_code == 200, r.text
    return r.json()


def _d(point, key):
    return Decimal(str(point[key]))


def test_today_splits_into_the_four_groups(world):
    today = _history(world)[-1]
    assert {k: _d(today, k) for k in GROUPS} == {
        "cash": Decimal("5500.00"),        # bank 2,500 + manual savings 3,000
        "investments": Decimal("5000.00"),  # pension 5,000 + ISA 0
        "property": Decimal("201000.00"),   # house 200,000 + other 1,000
        "debt": Decimal("6200.00"),         # card 700 + loan 4,000 + old loan asset 1,500
    }
    assert _d(today, "net_worth") == Decimal("205300.00")


def test_the_groups_add_up_to_net_worth_on_every_point(world):
    points = _history(world, months=6)
    assert len(points) == 7
    for p in points:
        total = _d(p, "cash") + _d(p, "investments") + _d(p, "property") - _d(p, "debt")
        assert total == _d(p, "net_worth"), p["date"]


def test_without_investments_the_figure_stays_but_leaves_net_worth(world):
    with_inv = _history(world, months=3)
    without = _history(world, months=3, include_investments="false")
    for a, b in zip(with_inv, without):
        assert [_d(a, k) for k in GROUPS] == [_d(b, k) for k in GROUPS], a["date"]
        assert _d(a, "net_worth") - _d(b, "net_worth") == _d(a, "investments")
        assert _d(b, "cash") + _d(b, "property") - _d(b, "debt") == _d(b, "net_worth")


def test_an_asset_tracked_later_counts_from_its_first_value(world):
    # The house was first valued 90 days ago: absent from points before that.
    points = _history(world, months=6)
    old = [p for p in points if p["date"] < (TODAY - timedelta(days=90)).isoformat()]
    assert old and all(_d(p, "property") == Decimal("0") for p in old)


def test_an_unknown_asset_type_counts_in_property_not_nowhere(world):
    def boat_to_unknown():
        asset = world.db.query(Asset).filter(Asset.user_id == world.user.id, Asset.asset_type == "other").one()
        asset.asset_type = "submarine"
        world.db.commit()
    world.as_user(boat_to_unknown)
    today = _history(world)[-1]
    assert _d(today, "property") == Decimal("201000.00")
    assert _d(today, "net_worth") == Decimal("205300.00")


def test_a_legacy_debt_asset_valued_later_joins_debt_from_then(world):
    def value_old_loan():
        asset = world.db.query(Asset).filter(Asset.user_id == world.user.id, Asset.asset_type == "loan").one()
        world.db.add(AssetValuation(asset_id=asset.id, value=Decimal("-1200"), valued_at=TODAY))
        world.db.commit()
    world.as_user(value_old_loan)
    assert _d(_history(world)[-1], "debt") == Decimal("5900.00")


def test_a_card_in_credit_stays_in_cash_and_never_lowers_debt(world):
    # eng-b on #212: as total_owed, a card in credit doesn't offset debt.
    def card_in_credit():
        acc = _account(world.db, world.user.id, atype="CREDIT_CARD", name="Spare card", balance="-250")
        acc.provider_name = "AMEX"  # Amex owed is positive, so -250 is £250 in credit
        world.db.add(AccountSetting(user_id=world.user.id, account_id=acc.id, role="credit"))
        world.db.commit()
    before = _history(world)[-1]
    world.as_user(card_in_credit)
    after = _history(world)[-1]
    assert _d(after, "debt") == _d(before, "debt")
    assert _d(after, "cash") - _d(before, "cash") == _d(after, "net_worth") - _d(before, "net_worth")
    assert _d(after, "net_worth") != _d(before, "net_worth")


def test_an_asset_worth_less_than_nothing_counts_as_debt(world):
    # The balance sheet puts a negative asset under Loans and finance.
    world.asset("Old tab", "other", "-400", days_ago=1)
    today = _history(world)[-1]
    assert _d(today, "property") == Decimal("201000.00")
    assert _d(today, "debt") == Decimal("6600.00")
    assert _d(today, "net_worth") == Decimal("204900.00")
