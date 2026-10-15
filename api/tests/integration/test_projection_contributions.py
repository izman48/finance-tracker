"""A contribution never adds to net worth (T-12-0; owner, live P0, 2026-10-15).

The Wealth projection added an investment's unlinked monthly contribution to
the holding as if it were new money, on top of a surplus that never paid
for it, so net worth rose by the contribution every month. A contribution
only moves cash into the holding:

- linked: it is a bill, so the surplus already pays it and the holding gains it;
- unlinked (the legacy `monthly_contribution`): it now comes off the cash
  surplus in every mode and goes into the holding. If the payment is also
  inside measured spending, savings come out lower, never higher.

Invested money grows at its rate; cash does not. Owner's synthetic case:
income £1,000, commitments £400, budgets £300, ISA contribution £200 ->
net worth +£300 a month (not £500); with no contribution, still +£300.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core import user_crypto
from app.models import Asset, AssetValuation, Budget, CommitmentLink, CommitmentRule, User
from tests.clock import TODAY
from tests.integration.test_oauth import _bearer, _web_login
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

API = "/api/v1"


class World:
    def __init__(self, client, db, contribution="200", linked=False):
        self.client, self.db = client, db
        self.token = _web_login(client, "contrib@example.com")
        self.dek = _dek_from_token(self.token)
        self.user = db.query(User).filter(User.email == "contrib@example.com").one()
        self.as_user(lambda: self._seed(Decimal(contribution), linked))

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def _rule(self, label, amount, direction, days):
        rule = CommitmentRule(
            user_id=self.user.id, direction=direction, label=label, amount=Decimal(amount), cadence="monthly",
            next_date=TODAY + timedelta(days=days), source="manual", status="confirmed",
            is_payday=direction == "income",
        )
        self.db.add(rule)
        self.db.flush()
        return rule

    def _seed(self, contribution: Decimal, linked: bool):
        _account(self.db, self.user.id, name="Current", balance="2000")
        self._rule("Salary", "1000", "income", 10)
        self._rule("Rent", "400", "expense", 5)
        self.db.add(Budget(user_id=self.user.id, category="Groceries", limit_pounds=Decimal("300"), paused=False, active=True))
        isa = Asset(user_id=self.user.id, name="Test ISA", asset_type="isa", assumed_growth_pct=Decimal("0"),
                    monthly_contribution=None if linked else (contribution or None))
        self.db.add(isa)
        self.db.flush()
        self.db.add(AssetValuation(asset_id=isa.id, value=Decimal("5000"), valued_at=TODAY))
        if linked and contribution:
            bill = self._rule("Test ISA contribution", str(contribution), "expense", 7)
            self.db.add(CommitmentLink(user_id=self.user.id, commitment_id=bill.id, asset_id=isa.id,
                                       role="contribution", commitment_created=True, created_on=TODAY))
        self.db.commit()

    def projection(self, **params):
        res = self.client.get(f"{API}/analytics/net-worth-projection",
                              params={"annual_growth_pct": "0", "spending_source": "budgets", **params},
                              headers=_bearer(self.token))
        assert res.status_code == 200, res.text
        return res.json()


def _monthly_changes(p, months=12):
    values = [Decimal(pt["value"]) for pt in p["timeline"][: months + 1]]
    return [b - a for a, b in zip(values, values[1:])]


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("contribution", ["0", "200", "300", "500"])
def test_the_owners_case_net_worth_rises_by_300_a_month(client, db_session, contribution, linked):
    world = World(client, db_session, contribution=contribution, linked=linked)
    assert set(_monthly_changes(world.projection())) == {Decimal("300.00")}


def test_the_unlinked_contribution_moves_cash_into_the_holding(client, db_session):
    world = World(client, db_session, contribution="200")
    p = world.projection()
    basis = p["contribution_basis"]
    assert Decimal(basis["contributions_monthly"]) == Decimal("200.00")
    # The cash surplus pays it: 1,000 - 400 - 300 - 200.
    assert Decimal(basis["contribution"]) == Decimal("100.00")
    one, two = p["timeline"][1], p["timeline"][2]
    assert Decimal(two["assets"]) - Decimal(one["assets"]) == Decimal("200.00")  # the ISA gains it
    assert Decimal(two["invested"]) - Decimal(one["invested"]) == Decimal("100.00")  # the surplus left


def test_a_linked_contribution_is_a_bill_and_never_counted_twice(client, db_session):
    world = World(client, db_session, contribution="200", linked=True)
    basis = world.projection()["contribution_basis"]
    assert Decimal(basis["bills_monthly"]) == Decimal("600.00")
    assert Decimal(basis["contributions_monthly"]) == Decimal("0.00")
    assert Decimal(basis["contribution"]) == Decimal("100.00")


@pytest.mark.parametrize("params", [{"spending_source": "average"}, {"monthly_contribution": "250"}])
def test_every_mode_takes_the_contribution_off_cash(client, db_session, params):
    with_it = World(client, db_session, contribution="200").projection(**params)
    one, two = with_it["timeline"][1], with_it["timeline"][2]
    # Whatever the mode, the holding gains 200 and the 200 is not new money.
    assert Decimal(two["assets"]) - Decimal(one["assets"]) == Decimal("200.00")
    cash_and_invested = [Decimal(pt["cash"]) + Decimal(pt["invested"]) for pt in with_it["timeline"][:3]]
    change = Decimal(two["value"]) - Decimal(one["value"])
    assert change == cash_and_invested[2] - cash_and_invested[1] + Decimal("200.00")
    if "monthly_contribution" in params:
        assert change == Decimal("250.00")  # the typed figure is the whole monthly change


def test_invested_money_grows_and_cash_does_not(client, db_session):
    world = World(client, db_session, contribution="200")
    p = world.projection(annual_growth_pct="10")
    cash = {pt["cash"] for pt in p["timeline"][:13]}
    assert len(cash) == 1  # held flat
    invested = [Decimal(pt["invested"]) for pt in p["timeline"][1:13]]
    gains = [b - a for a, b in zip(invested, invested[1:])]
    assert all(g > Decimal("100.00") for g in gains)  # 100 in each month, plus growth on what is there
    assert gains == sorted(gains)


def test_a_contribution_bigger_than_the_surplus_drains_cash_and_creates_nothing(client, db_session):
    # Surplus 300 (1,000 - 400 - 300), contribution 500: 200 a month comes out
    # of cash, the ISA gains 500, net worth still +300.
    p = World(client, db_session, contribution="500").projection()
    one, two = p["timeline"][1], p["timeline"][2]
    assert Decimal(two["value"]) - Decimal(one["value"]) == Decimal("300.00")
    assert Decimal(two["cash"]) - Decimal(one["cash"]) == Decimal("-200.00")
    assert Decimal(two["assets"]) - Decimal(one["assets"]) == Decimal("500.00")


# --- the "None" spending choice is gone (owner, 2026-10-15; sec-1 T-12-0) ----

def test_spending_none_is_refused(client, db_session):
    world = World(client, db_session)
    res = world.client.get(f"{API}/analytics/net-worth-projection", params={"spending_source": "none"},
                           headers=_bearer(world.token))
    assert res.status_code == 422


def test_subtract_spending_false_is_ignored_never_no_spending(client, db_session):
    world = World(client, db_session)
    for params in ({}, {"spending_source": "budgets"}):
        assert world.projection(**params, subtract_spending="false") == world.projection(**params)
    res = world.client.get(f"{API}/analytics/net-worth-projection", params={"subtract_spending": "false"},
                           headers=_bearer(world.token))
    legacy = res.json()["contribution_basis"]
    assert Decimal(legacy["spending_applied"]) == Decimal("300.00")  # budgets, then the average
    assert legacy["spending_subtracted"] is True


def test_a_negative_spending_estimate_is_refused(client, db_session):
    world = World(client, db_session)
    res = world.client.get(f"{API}/analytics/net-worth-projection",
                           params={"spending_source": "average", "monthly_spending": "-500"},
                           headers=_bearer(world.token))
    assert res.status_code == 422
