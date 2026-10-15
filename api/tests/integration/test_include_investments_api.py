"""Input bounds and "Include investments" (T-11-4c; sec T-11-4).

Holding inputs outside the engine's bounds are refused with 422: growth %
-100..50, values ±10,000,000, contributions 0..10,000,000, a projection
target ±100,000,000, and `include_investments` only "true" or "false".
`include_investments=false` on net worth history and the projection drops
only the investment kinds (owner D1: isa, investment, pension, crypto);
liabilities, property, savings and cash don't move, and neither does
safe-to-spend.

Synthetic figures only.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core import user_crypto
from app.models import Liability, User
from tests.clock import TODAY
from tests.integration.test_oauth import _bearer, _web_login
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

API = "/api/v1"


class World:
    def __init__(self, client, db, email="holdings@example.com"):
        self.client, self.db = client, db
        self.token = _web_login(client, email)
        self.h = _bearer(self.token)
        self.dek = _dek_from_token(self.token)
        self.user = db.query(User).filter(User.email == email).one()

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def asset(self, name, asset_type, value, days_ago=0, **extra):
        body = {"name": name, "asset_type": asset_type, "value": value,
                "valued_at": (TODAY - timedelta(days=days_ago)).isoformat(), **extra}
        r = self.client.post(f"{API}/assets", json=body, headers=self.h)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def value(self, asset_id, value, days_ago=0):
        r = self.client.post(f"{API}/assets/{asset_id}/valuations", headers=self.h,
                             json={"value": value, "valued_at": (TODAY - timedelta(days=days_ago)).isoformat()})
        assert r.status_code == 201, r.text

    def projection(self, **params):
        return self.client.get(f"{API}/holdings/projection", params=params, headers=self.h)

    def everything(self):
        """An ISA and a pension (investments), a house, savings, a legacy
        loan asset, a liability and a bank account."""
        isa = self.asset("Test ISA", "isa", "0", assumed_growth_pct="7", monthly_contribution="1000")
        self.asset("Test Pension", "pension", "5000", days_ago=40, assumed_growth_pct="5")
        self.asset("Test House", "property", "200000", days_ago=90, assumed_growth_pct="2")
        self.asset("Test Saver", "savings", "3000", days_ago=10)
        self.asset("Old loan", "loan", "-1500", days_ago=20)

        def bank_and_loan():
            _account(self.db, self.user.id, name="Current", balance="2500")
            self.db.add(Liability(user_id=self.user.id, kind="loan", lender="Lender T", balance=Decimal("4000"),
                                  balance_as_of=TODAY - timedelta(days=3), apr=Decimal("6"),
                                  payment=Decimal("150"), start_date=TODAY + timedelta(days=8)))
            self.db.commit()
        self.as_user(bank_and_loan)
        return isa


@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


class TestBounds:
    @pytest.mark.parametrize("field,value", [
        ("assumed_growth_pct", "-100.01"), ("assumed_growth_pct", "50.01"),
        ("monthly_contribution", "10000000.01"), ("value", "10000000.01"), ("value", "-10000000.01"),
    ])
    def test_asset_inputs_out_of_bounds_are_422(self, world, field, value):
        body = {"name": "X", "asset_type": "isa", "value": "1", field: value}
        assert world.client.post(f"{API}/assets", json=body, headers=world.h).status_code == 422

    def test_minus_100_percent_is_accepted(self, world):
        world.asset("Test ISA", "isa", "1000", assumed_growth_pct="-100")

    def test_a_valuation_out_of_bounds_is_422(self, world):
        isa = world.asset("Test ISA", "isa", "1")
        r = world.client.post(f"{API}/assets/{isa}/valuations", json={"value": "10000000.01"}, headers=world.h)
        assert r.status_code == 422

    def test_an_update_out_of_bounds_is_422(self, world):
        isa = world.asset("Test ISA", "isa", "1")
        r = world.client.patch(f"{API}/assets/{isa}", json={"assumed_growth_pct": "-101"}, headers=world.h)
        assert r.status_code == 422

    @pytest.mark.parametrize("params", [
        {"annual_growth_pct": "-100.01"}, {"annual_growth_pct": "51"},
        {"monthly_contribution": "10000000.01"}, {"monthly_spending": "10000000.01"},
        {"target_amount": "100000000.01"}, {"include_investments": "maybe"},
    ])
    def test_projection_inputs_out_of_bounds_are_422(self, world, params):
        r = world.client.get(f"{API}/analytics/net-worth-projection", params=params, headers=world.h)
        assert r.status_code == 422

    @pytest.mark.parametrize("value", ["yes", "1", "on", "False"])
    def test_include_investments_takes_only_true_or_false(self, world, value):
        r = world.client.get(f"{API}/analytics/net-worth-history", params={"include_investments": value},
                             headers=world.h)
        assert r.status_code == 422


class TestIncludeInvestments:
    def _history(self, world, **params):
        r = world.client.get(f"{API}/analytics/net-worth-history", params={"months": 3, **params}, headers=world.h)
        assert r.status_code == 200, r.text
        return r.json()

    def test_history_without_investments_drops_only_investments(self, world):
        world.everything()
        on, off = self._history(world), self._history(world, include_investments="false")
        for a, b in zip(on, off):
            assert Decimal(a["bank"]) == Decimal(b["bank"])
            assert Decimal(a["liabilities"]) == Decimal(b["liabilities"])
        # Today: investments are the ISA (0) and the pension (5000).
        assert Decimal(on[-1]["assets"]) - Decimal(off[-1]["assets"]) == Decimal("5000")
        assert Decimal(off[-1]["assets"]) == Decimal("201500")  # house + saver - old loan

    def test_the_default_is_today_with_investments(self, world):
        world.everything()
        assert self._history(world) == self._history(world, include_investments="true")

    def test_projection_without_investments_drops_only_investments(self, world):
        world.everything()

        def proj(**p):
            r = world.client.get(f"{API}/analytics/net-worth-projection",
                                 params={"monthly_contribution": "0", **p}, headers=world.h)
            assert r.status_code == 200, r.text
            return r.json()
        on, off = proj(), proj(include_investments="false")
        assert [p["liabilities"] for p in on["timeline"]] == [p["liabilities"] for p in off["timeline"]]
        assert [p["cash"] for p in on["timeline"]] == [p["cash"] for p in off["timeline"]]
        assert Decimal(on["current_net_worth"]) - Decimal(off["current_net_worth"]) == Decimal("5000")
        assert {a["name"] for a in off["asset_assumptions"]} == {"Test House", "Test Saver", "Old loan"}

    def test_safe_to_spend_and_the_summary_do_not_take_it(self, world):
        world.everything()
        a = world.client.get(f"{API}/analytics/summary", headers=world.h).json()
        b = world.client.get(f"{API}/analytics/summary", params={"include_investments": "false"},
                             headers=world.h).json()
        assert a == b
