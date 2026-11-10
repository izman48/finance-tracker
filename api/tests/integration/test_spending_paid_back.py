"""Paid-back marks in Spending: the purchases lens, the drill and the trend
(T-03-4 P3; PRD T-03-1 v2, ACs 3, 8 and 32; T-03-2 decisions T8, T9).

The same rule as budgets (`services/paid_back.py`), over the range shown: a
spend mark nets the spend, in its own kind (card or cash) and month; a
category mark nets the category in the range or month its credit arrived,
never below £0, and only with no account or kind filter (a category mark has
neither). The money-out lens never reads marks.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.models import RepaymentMark
from app.services import analytics_service as svc
from app.services.analytics.projections import derived_contribution
from app.services.budget_spend import budget_spend
from tests.integration.test_budget_spend import World as SpendWorld
from tests.integration.test_oauth import _bearer, _web_login
from tests.integration.test_transactions_endpoint import _account, _tx

API = "/api/v1"
TODAY = date(2026, 11, 15)
OCT, NOV = (date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 11, 1), TODAY)


class World(SpendWorld):
    """A current account and a card; dinner on the card on 10 October."""

    def __init__(self, client, db, email="spending@example.com"):
        super().__init__(client, db, email)
        self.client = client

        def make():
            self.current = _account(db, self.user.id, name="Current", balance="3000")
            self.card = _account(db, self.user.id, atype="CREDIT_CARD", name="Card", balance="200")
        self.as_user(make)

    def purchase(self, amount, on=date(2026, 10, 10), category="Eating out", merchant="Pizza Express", card=True):
        return self.as_user(lambda: _tx(self.db, self.card if card else self.current, amount, on,
                                        merchant=merchant, category=category))

    def credit(self, amount, on=date(2026, 10, 12), merchant="SAM"):
        return self.as_user(lambda: _tx(self.db, self.current, amount, on, ttype="credit", merchant=merchant))

    def mark(self, credit, amount, spend=None, category=None):
        def make():
            self.db.add(RepaymentMark(user_id=self.user.id, credit_transaction_id=credit.id,
                                      spend_transaction_id=spend.id if spend else None, category=category,
                                      amount=Decimal(amount), label="Sam, Pizza Express", created_via="mcp"))
            self.db.commit()
        self.as_user(make)

    def dinner_example(self, against="spend"):
        dinner = self.purchase("200.00")
        target = {"spend": dinner} if against == "spend" else {"category": "Eating out"}
        self.mark(self.credit("60.00"), "60.00", **target)
        self.mark(self.credit("50.00", on=date(2026, 10, 15), merchant="JO"), "50.00", **target)
        return dinner

    def purchases(self, frm=OCT[0], to=OCT[1], **kw):
        return self.as_user(lambda: svc.get_spending(self.db, self.user, "custom", frm, to, lens="purchases", **kw))

    def drill(self, frm=OCT[0], to=OCT[1], **kw):
        return self.as_user(lambda: svc.spending_transactions(self.db, self.user, "custom", frm, to, **kw))

    def trend(self):
        return {m["month"]: m for m in self.as_user(lambda: svc.get_spending_trend(self.db, self.user, months=3))["months"]}


@pytest.fixture
def w(client, db_session, today_is):
    today_is(TODAY)
    return World(client, db_session)


def _categories(body) -> dict:
    return {c["category"]: c["total"] for c in body["by_category"]}


# --- the purchases lens ---------------------------------------------------------------


def test_spend_marks_net_the_spend_in_its_own_kind(w):
    w.dinner_example("spend")
    body = w.purchases()
    assert _categories(body) == {"Eating out": Decimal("90.00")}
    assert (body["total_spent"], body["charged_to_credit"], body["paid_from_cash"]) == (
        Decimal("90.00"), Decimal("90.00"), Decimal(0))
    assert body["top_merchants"] == [{"merchant": "Pizza Express", "total": Decimal("90.00")}]
    assert body["paid_back_by_others"] == 0


def test_category_marks_net_the_category_and_the_total_reconciles(w):
    """T8: total = card + cash - paid back by others."""
    w.dinner_example("category")
    body = w.purchases()
    assert _categories(body) == {"Eating out": Decimal("90.00")}
    assert body["by_category"][0]["paid_back_by_others"] == Decimal("110.00")
    assert body["paid_back_by_others"] == Decimal("110.00")
    assert body["total_spent"] == body["charged_to_credit"] + body["paid_from_cash"] - body["paid_back_by_others"]
    assert body["total_spent"] == Decimal("90.00")


def test_a_category_mark_beyond_the_ranges_spending_is_excess_not_income(w):
    """Worked example, cycle 2 dates: £40 against Eating out, nothing spent."""
    w.purchase("12.00", on=date(2026, 11, 2), category="Groceries", merchant="Tesco")
    w.mark(w.credit("40.00", on=date(2026, 11, 3)), "40.00", category="Eating out")
    body = w.purchases(*NOV)
    assert _categories(body) == {"Groceries": Decimal("12.00")}
    assert body["paid_back_by_others"] == 0 and body["total_spent"] == Decimal("12.00")
    assert body["paid_back_excess"] == [{"category": "Eating out", "amount": Decimal("40.00")}]


def test_category_marks_are_skipped_under_an_account_or_kind_filter(w):
    """T8: a category mark has no account or kind; spend marks still net."""
    w.dinner_example("category")
    card_only = w.purchases(kind="credit")
    assert _categories(card_only) == {"Eating out": Decimal("200.00")}
    assert card_only["paid_back_by_others"] == 0


def test_a_later_repayment_nets_the_spend_in_its_own_range(w):
    """AC-3 (Spending): £40 more, from a November credit, for October's dinner."""
    dinner = w.dinner_example("spend")
    w.mark(w.credit("40.00", on=date(2026, 11, 3)), "40.00", spend=dinner)
    assert _categories(w.purchases()) == {"Eating out": Decimal("50.00")}
    assert w.purchases(*NOV)["by_category"] == []


def test_the_money_out_lens_never_reads_marks(w):
    w.purchase("200.00", card=False)
    before = w.as_user(lambda: svc.get_spending(w.db, w.user, "custom", *OCT))
    w.mark(w.credit("60.00"), "60.00", category="Eating out")
    after = w.as_user(lambda: svc.get_spending(w.db, w.user, "custom", *OCT))
    assert after == before


def test_spending_and_budgets_agree_with_marks(w):
    """Three-sources rule, with spend and category marks in play."""
    w.dinner_example("spend")
    w.purchase("30.00", on=date(2026, 10, 20), category="Groceries", merchant="Tesco", card=False)
    w.mark(w.credit("10.00", on=date(2026, 10, 21)), "10.00", category="Groceries")
    budgets = w.as_user(lambda: budget_spend(w.db, w.user, *OCT)).by_category
    assert _categories(w.purchases(exclude_commitments=True)) == budgets


# --- the drill ------------------------------------------------------------------------


def test_drill_rows_show_paid_back_and_what_counts(w):
    """AC-32 (API): "£110.00 of £200.00 paid back. Counts as £90.00." """
    w.dinner_example("spend")
    [row] = w.drill(category="Eating out")
    assert (row["amount"], row["paid_back"], row["counted"]) == (
        Decimal("200.00"), Decimal("110.00"), Decimal("90.00"))


def test_drill_rows_with_no_marks_count_in_full(w):
    w.purchase("200.00")
    [row] = w.drill()
    assert (row["paid_back"], row["counted"]) == (Decimal(0), Decimal("200.00"))


# --- the trend and Wealth ---------------------------------------------------------------


def test_the_trend_nets_spend_marks_in_the_spends_month(w):
    """AC-8: a November repayment of October's dinner lowers October."""
    dinner = w.purchase("200.00")
    w.mark(w.credit("60.00", on=date(2026, 11, 3)), "60.00", spend=dinner)
    trend = w.trend()
    assert (trend["2026-10"]["total"], trend["2026-10"]["charged_to_credit"]) == (
        Decimal("140.00"), Decimal("140.00"))
    assert trend["2026-11"]["total"] == 0


def test_the_trend_nets_category_marks_in_the_credits_month_floored(w):
    """AC-8: category marks net by the credit's month, never below £0 per
    category and month."""
    w.purchase("200.00")                                         # October
    w.purchase("25.00", on=date(2026, 11, 2), card=False)        # November
    w.mark(w.credit("60.00"), "60.00", category="Eating out")    # October credit
    w.mark(w.credit("40.00", on=date(2026, 11, 3)), "40.00", category="Eating out")  # November: £15 excess
    trend = w.trend()
    assert (trend["2026-10"]["total"], trend["2026-10"]["paid_back_by_others"]) == (
        Decimal("140.00"), Decimal("60.00"))
    assert (trend["2026-11"]["total"], trend["2026-11"]["paid_back_by_others"]) == (Decimal(0), Decimal("25.00"))


def test_wealth_average_spending_reads_the_netted_trend(w):
    """AC-8: marked months read lower in the Wealth projection too."""
    w.dinner_example("spend")
    sampled = {m["month"]: m["total"] for m in w.as_user(lambda: derived_contribution(w.db, w.user))["sampled_months"]}
    assert sampled["2026-10"] == Decimal("90.00")


def test_the_spending_routes_carry_the_new_fields(w):
    w.dinner_example("category")
    web = _bearer(_web_login(w.client, "spending@example.com"))
    params = {"period": "custom", "frm": OCT[0].isoformat(), "to": OCT[1].isoformat()}
    body = w.client.get(f"{API}/analytics/spending", params={**params, "lens": "purchases"}, headers=web).json()
    assert Decimal(body["paid_back_by_others"]) == Decimal("110.00") and body["paid_back_excess"] == []
    assert Decimal(body["by_category"][0]["paid_back_by_others"]) == Decimal("110.00")
    [row] = w.client.get(f"{API}/analytics/spending/transactions", params=params, headers=web).json()
    assert (Decimal(row["paid_back"]), Decimal(row["counted"])) == (0, Decimal("200.00"))
    months = w.client.get(f"{API}/analytics/spending/trend", params={"months": 3}, headers=web).json()["months"]
    assert Decimal({m["month"]: m for m in months}["2026-10"]["paid_back_by_others"]) == Decimal("110.00")
