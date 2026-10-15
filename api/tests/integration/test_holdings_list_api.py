"""Claude's read-only view of holdings (T-11-7; sec T-11-7).

`GET /api/v1/holdings` (finance:read) lists each holding with exactly the
allowed keys: id, name, kind, value, value_as_of, growth_pct,
monthly_contribution, linked and projected values at fixed horizons. No
user id, history, commitment ids or timestamps. At most 100, with
`truncated` saying when more exist. `investments_total` in the summary uses
the same investment kinds as "Include investments" (owner D1), so the two
never disagree. Synthetic figures only.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import Asset, AssetValuation
from tests.clock import TODAY
from tests.integration.test_contribution_link_api import World
from tests.integration.test_linked_commitment_guards import API, _bearer

HOLDING_KEYS = {"id", "name", "kind", "value", "value_as_of", "growth_pct", "monthly_contribution", "linked",
                "projected"}
HORIZON_KEYS = {"1y", "5y", "10y"}


@pytest.fixture
def world(client, db_session):
    return World(client, db_session, email="claude-holdings@example.com")


def _list(world, token=None):
    r = world.client.get(f"{API}/holdings", headers=_bearer(token or world.mcp))
    assert r.status_code == 200, r.text
    return r.json()


def _isa(world, value="0", growth="7", name="Example ISA"):
    res = world.client.post(f"{API}/assets", json={"name": name, "asset_type": "isa", "value": value,
                                                   "assumed_growth_pct": growth}, headers=_bearer(world.web))
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_the_response_keys_are_exactly_the_allowed_ones(world):
    world.put(_isa(world), amount="1000.00")
    body = _list(world)
    assert set(body) == {"holdings", "count", "truncated"}
    assert body["count"] == 1 and body["truncated"] is False
    for h in body["holdings"]:
        assert set(h) == HOLDING_KEYS
        assert set(h["projected"]) == HORIZON_KEYS


def test_an_investment_reads_back_its_terms_and_engine_forecast(world):
    isa = _isa(world)
    world.put(isa, amount="1000.00")
    (h,) = [x for x in _list(world)["holdings"] if x["id"] == isa]
    assert (h["name"], h["kind"], h["value"], h["value_as_of"]) == ("Example ISA", "isa", "0.00", TODAY.isoformat())
    assert (h["growth_pct"], h["monthly_contribution"], h["linked"]) == ("7.00", "1000.00", True)
    # The engine's figure: £0, £1,000 a month, 7% (effective annual), 10 years.
    assert h["projected"]["10y"] == "171051.73"


def test_debts_are_never_listed(world):
    # sec / lead (2026-10-15): Claude doesn't read lender names; debt reaches
    # it only as liabilities_total in cashflow_summary.
    world.loan()
    world.client.post(f"{API}/assets", json={"name": "Old loan", "asset_type": "loan", "value": "-1500"},
                      headers=_bearer(world.web))
    _isa(world)
    body = _list(world)
    assert [h["kind"] for h in body["holdings"]] == ["isa"] and body["count"] == 1
    assert "Example Bank" not in str(body) and "Old loan" not in str(body)


def test_growth_not_set_reads_null_not_the_default(world):
    res = world.client.post(f"{API}/assets", json={"name": "No rate", "asset_type": "pension", "value": "100"},
                            headers=_bearer(world.web))
    (h,) = [x for x in _list(world)["holdings"] if x["id"] == res.json()["id"]]
    assert h["growth_pct"] is None


def test_nothing_beyond_the_allowed_fields_leaks(world):
    isa = _isa(world)
    world.put(isa, amount="1000.00")
    text = str(_list(world))
    assert str(world.user.id) not in text
    for row in world.rows():
        assert str(row.commitment_id) not in text


def test_another_users_holdings_are_never_listed(world, bob):
    _isa(bob, name="Bob ISA")
    assert _list(world)["holdings"] == []


def test_the_list_is_capped_at_100_and_says_so(world):
    def many():
        for n in range(101):
            asset = Asset(user_id=world.user.id, name=f"Fund {n:03}", asset_type="investment")
            world.db.add(asset)
            world.db.flush()
            world.db.add(AssetValuation(asset_id=asset.id, value=Decimal("10"), valued_at=TODAY - timedelta(days=1)))
        world.db.commit()
    with world.as_user():
        many()
    body = _list(world)
    assert (body["count"], body["truncated"], len(body["holdings"])) == (101, True, 100)


def test_the_web_session_can_read_it_too(world):
    _isa(world)
    assert len(_list(world, token=world.web)["holdings"]) == 1


def test_investments_total_is_the_investment_kinds_only(world):
    _isa(world, value="18000")
    for name, kind, value in (("Example Pension", "pension", "10000"), ("Example House", "property", "250000"),
                              ("Example Saver", "savings", "3000")):
        world.client.post(f"{API}/assets", json={"name": name, "asset_type": kind, "value": value},
                          headers=_bearer(world.web))
    summary = world.summary(token=world.mcp)
    assert Decimal(summary["investments_total"]) == Decimal("28000.00")
    listed = sum(Decimal(h["value"]) for h in _list(world)["holdings"] if h["kind"] in {"isa", "investment",
                                                                                         "pension", "crypto"})
    assert Decimal(summary["investments_total"]) == listed


def test_investments_total_includes_contributions_paid_since_the_last_value(world):
    # The same value today as net worth, so the two figures never disagree.
    isa = _isa(world, value="1000")
    world.put(isa, amount="500.00")
    from tests.integration.test_contribution_link_api import _add_months, _backdate
    _backdate(world, uuid.UUID(isa), valued=TODAY - timedelta(days=20), linked=TODAY - timedelta(days=20),
              next_date=_add_months(TODAY - timedelta(days=5), 1))
    assert Decimal(world.summary()["investments_total"]) == Decimal("1500.00")
    assert Decimal(world.summary()["net_worth"]) == Decimal("1500.00")


def test_no_investments_is_a_zero_total(world):
    assert Decimal(world.summary()["investments_total"]) == Decimal("0")


@pytest.fixture
def bob(client, db_session):
    return World(client, db_session, email="claude-holdings-bob@example.com")


def test_a_negative_investment_is_debt_not_listed_or_in_the_total(world):
    # Lead decision (sec-2, fail-safe): an investment worth less than nothing
    # is Debt, as in net worth's groups.
    _isa(world, value="5000")
    world.client.post(f"{API}/assets", json={"name": "Margin account", "asset_type": "investment", "value": "-300"},
                      headers=_bearer(world.web))
    body = _list(world)
    assert [h["name"] for h in body["holdings"]] == ["Example ISA"] and body["count"] == 1
    assert Decimal(world.summary()["investments_total"]) == Decimal("5000.00")


def test_investments_total_is_the_history_investments_figure(world):
    # sec T-11-7: the summary's investments_total and net worth's
    # Investments group (and what "Include investments" removes) never
    # disagree, including a linked contribution paid since the last value and
    # a negative investment (Debt in both).
    isa = _isa(world, value="1000")
    world.put(isa, amount="500.00")
    from tests.integration.test_contribution_link_api import _add_months, _backdate
    _backdate(world, uuid.UUID(isa), valued=TODAY - timedelta(days=20), linked=TODAY - timedelta(days=20),
              next_date=_add_months(TODAY - timedelta(days=5), 1))
    for name, kind, value in (("Example Pension", "pension", "2500"), ("Margin", "investment", "-300"),
                              ("Example House", "property", "90000")):
        world.client.post(f"{API}/assets", json={"name": name, "asset_type": kind, "value": value},
                          headers=_bearer(world.web))
    total = Decimal(world.summary()["investments_total"])
    history = world.client.get(f"{API}/analytics/net-worth-history", headers=_bearer(world.web)).json()
    without = world.client.get(f"{API}/analytics/net-worth-history", params={"include_investments": "false"},
                               headers=_bearer(world.web)).json()
    assert total == Decimal("4000.00")  # 1,000 + 500 paid + 2,500; the -300 is Debt
    assert total == Decimal(str(history[-1]["investments"]))
    assert total == Decimal(str(history[-1]["net_worth"])) - Decimal(str(without[-1]["net_worth"]))
