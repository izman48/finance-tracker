"""The Wealth projection can use budgets as its spending figure (T-10-15b;
owner 2026-10-15; sec T-10-15 criteria).

`spending_source` = budgets / average / none. Budgets = the total of active,
unpaused budget limits a month, read through `cycle_budgets` (the function
the Cashflow budget line uses). No active budgets, or a £0 total, falls back
to the average and the basis says so: never "£0 spending". Without
`spending_source` the result is today's. When it is sent, it wins over the
old `subtract_spending`; `monthly_spending` only applies to `average`.
Nothing is stored; safe-to-spend, forecast and summary don't move.

Synthetic fixture: income £2,500, rent £950, budgets £500 + £390 = £890.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core import user_crypto
from app.models import Budget, CommitmentRule, User
from app.services.budgets import cycle_budgets
from tests.clock import TODAY
from tests.integration.test_oauth import _bearer, _web_login
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

API = "/api/v1"


class World:
    def __init__(self, client, db):
        self.client, self.db = client, db
        self.token = _web_login(client, "projection@example.com")
        self.dek = _dek_from_token(self.token)
        self.user = db.query(User).filter(User.email == "projection@example.com").one()
        self.as_user(self._seed)

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def _seed(self):
        _account(self.db, self.user.id, name="Current", balance="3000")
        for label, amount, direction, days in (("Salary", "2500", "income", 12), ("Rent", "950", "expense", 5)):
            self.db.add(CommitmentRule(
                user_id=self.user.id, direction=direction, label=label, amount=Decimal(amount), cadence="monthly",
                next_date=TODAY + timedelta(days=days), source="manual", status="confirmed",
                is_payday=direction == "income",
            ))
        self.db.commit()

    def budget(self, category, limit, paused=False, active=True):
        def make():
            self.db.add(Budget(user_id=self.user.id, category=category, limit_pounds=Decimal(limit),
                               paused=paused, active=active))
            self.db.commit()
        self.as_user(make)

    def projection(self, **params):
        res = self.client.get(f"{API}/analytics/net-worth-projection", params=params, headers=_bearer(self.token))
        assert res.status_code == 200, res.text
        return res.json()

    def get(self, path):
        return self.client.get(f"{API}{path}", headers=_bearer(self.token)).json()


@pytest.fixture
def world(client, db_session):
    return World(client, db_session)


def _legacy_view(p: dict) -> dict:
    """Everything a client could read before T-10-15 (the new basis keys aside)."""
    basis = {k: v for k, v in (p["contribution_basis"] or {}).items()
             if k not in {"spending_choice", "spending_used", "budgets_monthly", "budgets_fallback"}}
    return {**p, "contribution_basis": basis}


def test_budgets_are_the_monthly_spending(world):
    world.budget("Groceries", "500")
    world.budget("Eating out", "390")
    basis = world.projection(spending_source="budgets")["contribution_basis"]
    assert Decimal(basis["income_monthly"]) == Decimal("2500.00")
    assert Decimal(basis["bills_monthly"]) == Decimal("950.00")
    assert Decimal(basis["spending_applied"]) == Decimal("890.00")
    assert Decimal(basis["contribution"]) == Decimal("660.00")  # 2,500 − 950 − 890
    assert (basis["spending_choice"], basis["spending_used"], basis["budgets_fallback"]) == ("budgets", "budgets", False)
    assert Decimal(basis["budgets_monthly"]) == Decimal("890.00")


def test_every_later_month_uses_the_same_budget_total(world):
    world.budget("Groceries", "890")
    with_budgets = world.projection(spending_source="budgets", target_amount="1000000")
    none = world.projection(spending_source="none", target_amount="1000000")
    # Same cashflow, £890 less each month: the invested gap grows by about £890 a month.
    gaps = [Decimal(n["invested"]) - Decimal(b["invested"]) for n, b in zip(none["timeline"][1:4], with_budgets["timeline"][1:4])]
    assert gaps[0] == Decimal("890.00")
    assert gaps[1] > gaps[0] + Decimal("889") and gaps[2] > gaps[1] + Decimal("889")


def test_paused_and_removed_budgets_are_not_counted(world):
    world.budget("Groceries", "500")
    world.budget("Eating out", "390", paused=True)
    world.budget("Travel", "300", active=False)
    basis = world.projection(spending_source="budgets")["contribution_basis"]
    assert Decimal(basis["spending_applied"]) == Decimal("500.00")


def test_the_budget_figure_is_the_cashflow_budget_lines_total(world):
    world.budget("Groceries", "500")
    world.budget("Eating out", "390", paused=True)
    basis = world.projection(spending_source="budgets")["contribution_basis"]
    total = world.as_user(lambda: cycle_budgets(world.db, world.user, TODAY).total_limit)
    assert Decimal(basis["budgets_monthly"]) == total


@pytest.mark.parametrize("setup", ["none", "all_paused", "all_removed"])
def test_no_active_budgets_falls_back_to_the_average_never_zero(world, setup):
    if setup == "all_paused":
        world.budget("Groceries", "500", paused=True)
    if setup == "all_removed":
        world.budget("Groceries", "500", active=False)
    p = world.projection(spending_source="budgets")
    avg = world.projection(spending_source="average")
    basis = p["contribution_basis"]
    assert (basis["spending_used"], basis["budgets_fallback"]) == ("average", True)
    assert Decimal(basis["budgets_monthly"]) == Decimal("0")
    assert _legacy_view(p)["timeline"] == _legacy_view(avg)["timeline"]
    assert Decimal(basis["spending_applied"]) == Decimal(basis["avg_spending_monthly"])


def test_average_and_none_give_todays_results(world):
    world.budget("Groceries", "890")
    assert _legacy_view(world.projection(spending_source="average")) == _legacy_view(world.projection())
    assert _legacy_view(world.projection(spending_source="none")) == _legacy_view(world.projection(subtract_spending="false"))
    est = world.projection(spending_source="average", monthly_spending="700")
    assert _legacy_view(est) == _legacy_view(world.projection(monthly_spending="700"))
    assert est["contribution_basis"]["spending_used"] == "estimate"


def test_without_spending_source_the_response_is_unchanged(world):
    world.budget("Groceries", "890")
    basis = world.projection()["contribution_basis"]
    assert basis["spending_choice"] is None and basis["spending_used"] is None and basis["budgets_monthly"] is None
    assert basis["spending_source"] == "measured"


def test_spending_source_wins_over_the_old_params(world):
    world.budget("Groceries", "890")
    # subtract_spending is ignored once spending_source is sent; monthly_spending only applies to average.
    assert _legacy_view(world.projection(spending_source="budgets", subtract_spending="false", monthly_spending="5")) == \
        _legacy_view(world.projection(spending_source="budgets"))
    assert _legacy_view(world.projection(spending_source="none", monthly_spending="700")) == \
        _legacy_view(world.projection(spending_source="none"))


@pytest.mark.parametrize("value", ["budget", "BUDGETS", "", "average; drop"])
def test_an_unknown_spending_source_is_422(world, value):
    res = world.client.get(f"{API}/analytics/net-worth-projection", params={"spending_source": value},
                           headers=_bearer(world.token))
    assert res.status_code == 422


def test_safe_to_spend_forecast_and_summary_do_not_move(world):
    before = (world.get("/analytics/summary"), world.get("/analytics/forecast"))
    world.budget("Groceries", "890")
    world.projection(spending_source="budgets")
    after_summary, after_forecast = world.get("/analytics/summary"), world.get("/analytics/forecast")
    for key in ("safe_to_spend", "net_worth", "committed_before_payday", "savable"):
        assert after_summary[key] == before[0][key], key
    assert [(p["date"], p["balance"]) for p in after_forecast["timeline"]] == \
        [(p["date"], p["balance"]) for p in before[1]["timeline"]]
