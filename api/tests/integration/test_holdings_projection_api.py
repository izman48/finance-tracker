"""The investment graphs' API (T-11-4c; ux T-11-2; sec T-11-4).

`GET /api/v1/holdings/projection` returns each investment (owner D1) and
their total: the valuations entered as history, then a monthly forecast
from the holding engine with "paid in" (value today plus the contributions
from today, ux A3). It is the same function as the target projection.

Synthetic figures only.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_include_investments_api import API, World


@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


class TestInvestmentGraph:
    def test_worked_example_in_10_years(self, world):
        world.asset("Test ISA", "isa", "0", assumed_growth_pct="7", monthly_contribution="1000")
        body = world.projection(months=120).json()
        (isa,) = body["holdings"]
        assert isa["forecast"][-1] == {
            "date": _add_months(TODAY, 120).isoformat(), "worth": "171051.73", "paid_in": "120000.00",
        }
        assert body["total"]["answer"] == {"months": 120, "worth_about": "171000", "paid_in": "120000"}

    def test_only_investment_kinds_are_listed_and_the_total_is_theirs(self, world):
        world.everything()
        body = world.projection(months=12).json()
        assert [h["name"] for h in body["holdings"]] == ["Test ISA", "Test Pension"]
        assert body["total"]["value_today"] == "5000.00"
        assert body["total"]["monthly_contribution"] == "1000.00"
        for i, point in enumerate(body["total"]["forecast"]):
            # The total is rounded once from exact values (the browser sums
            # nothing): within a penny per holding of the rounded parts.
            parts = sum(Decimal(h["forecast"][i]["worth"]) for h in body["holdings"])
            assert abs(Decimal(point["worth"]) - parts) <= Decimal("0.02")

    def test_history_is_the_valuations_entered(self, world):
        isa = world.asset("Test ISA", "isa", "1000", days_ago=200)
        world.value(isa, "1800", days_ago=100)
        world.value(isa, "2600", days_ago=0)
        (h,) = world.projection(months=12).json()["holdings"]
        assert h["history"] == [
            {"date": (TODAY - timedelta(days=d)).isoformat(), "worth": v}
            for d, v in ((200, "1000.00"), (100, "1800.00"), (0, "2600.00"))
        ]
        assert h["value_today"] == "2600.00" and h["value_as_of"] == TODAY.isoformat()

    def test_a_value_today_overwrite_rebases_the_forecast(self, world):
        isa = world.asset("Test ISA", "isa", "1000", days_ago=30, assumed_growth_pct="0", monthly_contribution="100")
        world.value(isa, "4000")
        (h,) = world.projection(months=2).json()["holdings"]
        assert [p["worth"] for p in h["forecast"]] == ["4000.00", "4100.00", "4200.00"]

    def test_one_holding_by_id(self, world):
        world.everything()
        pension = next(h for h in world.projection(months=1).json()["holdings"] if h["name"] == "Test Pension")
        body = world.projection(months=1, holding_id=pension["id"]).json()
        assert [h["name"] for h in body["holdings"]] == ["Test Pension"]
        assert body["total"]["value_today"] == "5000.00"

    def test_the_graph_matches_the_target_projection(self, world):
        """The same engine: the investments' worth on each month of the graph
        equals the target projection's assets minus the non-investments."""
        world.asset("Test ISA", "isa", "2000", assumed_growth_pct="6", monthly_contribution="300")
        graph = world.projection(months=24).json()["total"]["forecast"]
        proj = world.client.get(f"{API}/analytics/net-worth-projection",
                                params={"annual_growth_pct": "5", "monthly_contribution": "0"},
                                headers=world.h).json()["timeline"]
        assert [p["worth"] for p in graph[:25]] == [p["assets"] for p in proj[:25]]

    def test_a_holding_without_its_own_rate_uses_the_same_default_as_the_projection(self, world):
        world.asset("Test Pension", "pension", "8000")  # growth not set
        graph = world.projection(months=12, annual_growth_pct="3").json()["total"]["forecast"]
        proj = world.client.get(f"{API}/analytics/net-worth-projection",
                                params={"annual_growth_pct": "3", "monthly_contribution": "0"},
                                headers=world.h).json()["timeline"]
        assert [p["worth"] for p in graph] == [p["assets"] for p in proj[:13]]
        assert graph[12]["worth"] == "8240.00"

    def test_no_investments_is_an_empty_list(self, world):
        world.asset("Test House", "property", "100000")
        assert world.projection().json()["holdings"] == []


class TestSecurity:
    def test_another_users_holding_is_404(self, client, db_session):
        a = World(client, db_session, "owner-a@example.com")
        isa = a.asset("Test ISA", "isa", "1000")
        b = World(client, db_session, "other-b@example.com")
        assert b.projection(holding_id=isa).status_code == 404
        assert a.projection(holding_id=isa).status_code == 200

    def test_a_non_investment_holding_id_is_404(self, world):
        house = world.asset("Test House", "property", "100000")
        assert world.projection(holding_id=house).status_code == 404

    def test_unauthenticated_is_401(self, client):
        assert client.get(f"{API}/holdings/projection").status_code == 401

    @pytest.mark.parametrize("params", [
        {"months": 601}, {"months": 0}, {"holding_id": "../assets"}, {"holding_id": "1"},
        {"annual_growth_pct": "50.01"}, {"annual_growth_pct": "-100.01"},
    ])
    def test_bad_input_is_422(self, world, params):
        assert world.projection(**params).status_code == 422

    def test_the_largest_inputs_answer_quickly_and_finitely(self, world):
        import time
        for i in range(5):
            world.asset(f"Big {i}", "isa", "10000000", assumed_growth_pct="50", monthly_contribution="10000000")
        start = time.perf_counter()
        r = world.projection(months=600)
        assert r.status_code == 200 and time.perf_counter() - start < 1
        assert Decimal(r.json()["total"]["forecast"][-1]["worth"]).is_finite()


