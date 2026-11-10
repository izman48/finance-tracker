"""Paid-back marks in budgets (T-03-4 P2; PRD T-03-1 v2, ACs 1, 2, 4, 6, 7, 29,
30; T-03-2 decisions T5, T7).

A mark on a spend nets that spend in its own cycle, but only while the spend
still counts as spending. A mark on a category nets that category in the
cycle the credit arrived, never below £0; the rest is reported as excess,
never income. Every netted pound is listed under "Paid back by others".
Which categories may have a budget still reads gross spend (T5).
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import CommitmentRule, RepaymentMark, Transaction
from app.services import budgets as budgets_service
from app.services.budget_spend import budget_spend
from tests.clock import TODAY
from tests.integration.test_budgets_api import World as BudgetsWorld
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _account, _tx

API = "/api/v1"
CYCLE_START = TODAY - timedelta(days=20)  # payday 20 days ago
LAST_CYCLE = (CYCLE_START - timedelta(days=30), CYCLE_START - timedelta(days=1))


class World(BudgetsWorld):
    """A payday 20 days ago, a current account, and the PRD's worked example:
    a £200 Eating-out dinner this cycle, and Sam (£60) and Jo (£50) paying
    their share back a few days later."""

    def __init__(self, client, db, email="budgets@example.com"):
        super().__init__(client, db, email)

        def make():
            self.current = _account(db, self.user.id, name="Current", balance="3000")
            db.add(CommitmentRule(user_id=self.user.id, direction="income", label="Salary",
                                  amount=Decimal("2500"), cadence="monthly", next_date=CYCLE_START,
                                  source="manual", status="confirmed", is_payday=True))
            db.commit()
        self.as_user(make)

    def purchase(self, amount, days_ago=15, category="Eating out", merchant="Pizza Express") -> Transaction:
        return self.as_user(lambda: _tx(self.db, self.current, amount, TODAY - timedelta(days=days_ago),
                                        merchant=merchant, category=category))

    def credit(self, amount, days_ago=13, merchant="SAM") -> Transaction:
        return self.as_user(lambda: _tx(self.db, self.current, amount, TODAY - timedelta(days=days_ago),
                                        ttype="credit", merchant=merchant))

    def mark(self, credit, amount, spend=None, category=None, label="Sam £60, Pizza Express"):
        def make():
            self.db.add(RepaymentMark(
                user_id=self.user.id, credit_transaction_id=credit.id,
                spend_transaction_id=spend.id if spend else None, category=category,
                amount=Decimal(amount), label=label, created_via="mcp",
            ))
            self.db.commit()
        self.as_user(make)

    def budget(self, category="Eating out", limit=150):
        r = self.create(category, limit)
        assert r.status_code == 201, r.text

    def counts_as(self, tx, value):
        self.as_user(lambda: (setattr(tx, "counts_as_override", value), self.db.commit()))

    def spend_in(self, start=CYCLE_START, end=TODAY, **kw):
        return self.as_user(lambda: budget_spend(self.db, self.user, start, end, **kw))

    def dinner_example(self, against="spend"):
        """Sam £60 and Jo £50 marked to the dinner, or to Eating out."""
        dinner = self.purchase("200.00")
        sam, jo = self.credit("60.00"), self.credit("50.00", days_ago=10, merchant="JO")
        target = {"spend": dinner} if against == "spend" else {"category": "Eating out"}
        self.mark(sam, "60.00", label="Sam £60, Pizza Express", **target)
        self.mark(jo, "50.00", label="Jo £50, Pizza Express", **target)
        return dinner, sam, jo


@pytest.fixture
def w(client, db_session):
    return World(client, db_session)


# --- the counting rule ------------------------------------------------------------


def test_with_no_marks_nothing_is_paid_back(w):
    w.purchase("200.00")
    spend = w.spend_in()
    assert spend.by_category == spend.gross_by_category == {"Eating out": Decimal("200.00")}
    assert (spend.paid_back, spend.paid_back_marks, spend.paid_back_excess) == (Decimal(0), [], {})


def test_marks_on_a_category_net_it_the_same(w):
    w.dinner_example("category")
    spend = w.spend_in()
    assert spend.by_category == {"Eating out": Decimal("90.00")}
    assert spend.paid_back == Decimal("110.00") and spend.paid_back_excess == {}
    assert {m.against for m in spend.paid_back_marks} == {"Eating out"}


def test_a_spend_mark_nets_in_the_spends_cycle_not_the_credits(w):
    """AC-3 (budgets): a later repayment of last cycle's dinner leaves this
    cycle alone and nets the dinner's own cycle."""
    dinner = w.purchase("200.00", days_ago=35)  # last cycle
    w.mark(w.credit("40.00", days_ago=3), "40.00", spend=dinner)

    assert w.spend_in().paid_back == 0
    assert w.spend_in(*LAST_CYCLE).by_category == {"Eating out": Decimal("160.00")}


def test_a_category_mark_nets_in_the_cycle_the_credit_arrived(w):
    w.purchase("200.00", days_ago=35)  # last cycle
    w.purchase("30.00", days_ago=5)    # this cycle
    w.mark(w.credit("20.00", days_ago=3), "20.00", category="Eating out")

    assert w.spend_in(*LAST_CYCLE).by_category == {"Eating out": Decimal("200.00")}
    assert w.spend_in().by_category == {"Eating out": Decimal("10.00")}


def test_a_category_mark_beyond_what_is_left_after_spend_marks_is_excess(w):
    dinner = w.purchase("100.00")
    w.mark(w.credit("80.00"), "80.00", spend=dinner)
    w.mark(w.credit("50.00", days_ago=4, merchant="JO"), "50.00", category="Eating out")

    spend = w.spend_in()
    assert spend.by_category == {"Eating out": Decimal("0.00")}
    assert spend.paid_back_excess == {"Eating out": Decimal("30.00")}


def test_a_mark_on_a_spend_set_to_a_transfer_nets_nothing_until_set_back(w):
    """AC-29: the mark stays, but only counted spending is netted."""
    dinner, _, _ = w.dinner_example("spend")
    w.counts_as(dinner, "transfer")
    spend = w.spend_in()
    assert (spend.by_category, spend.paid_back) == ({}, Decimal(0))

    w.counts_as(dinner, None)
    assert w.spend_in().by_category == {"Eating out": Decimal("90.00")}


def test_a_credit_set_to_a_transfer_still_nets_its_mark(w):
    """AC-30: a friend's payment typed as a transfer is still a repayment."""
    _, sam, jo = w.dinner_example("category")
    w.counts_as(sam, "transfer")
    w.counts_as(jo, "transfer")
    assert w.spend_in().by_category == {"Eating out": Decimal("90.00")}


def test_proposed_marks_net_in_a_preview_and_are_not_saved(w, db_session):
    """T-03-2 T7: preview figures come from the same rule, with the proposed
    marks added."""
    dinner, sam = w.purchase("200.00"), w.credit("60.00")
    proposed = w.as_user(lambda: RepaymentMark(
        user_id=w.user.id, credit_transaction_id=sam.id, spend_transaction_id=dinner.id,
        amount=Decimal("60.00"), label="Sam £60, Pizza Express", created_via="mcp"))

    assert w.spend_in(extra_marks=[proposed]).by_category == {"Eating out": Decimal("140.00")}
    assert w.spend_in().by_category == {"Eating out": Decimal("200.00")}
    assert db_session.query(RepaymentMark).count() == 0


def test_another_users_marks_never_net(client, db_session, w):
    w.purchase("200.00")
    other = World(client, db_session, email="other@example.com")
    other.dinner_example("category")
    assert w.spend_in().by_category == {"Eating out": Decimal("200.00")}


def test_which_categories_may_have_a_budget_reads_gross_spend(w):
    """T5: £60 of Eating out, £50 of it a commitment. Marking £20 back must
    not make Eating out "mostly commitments" and so unbudgetable."""
    def bill():
        w.db.add(CommitmentRule(user_id=w.user.id, direction="expense", label="SUPPER CLUB",
                                amount=Decimal("50"), cadence="monthly", next_date=TODAY + timedelta(days=20),
                                source="manual", status="confirmed"))
        w.db.commit()
    w.as_user(bill)
    w.purchase("50.00", days_ago=10, merchant="SUPPER CLUB")
    pizza = w.purchase("60.00")
    w.mark(w.credit("20.00"), "20.00", spend=pizza)

    covered = w.as_user(lambda: budgets_service.commitment_covered(w.db, w.user, TODAY))
    budgetable = w.as_user(lambda: budgets_service.budgetable_categories(w.db, w.user, TODAY))
    assert "Eating out" not in covered and "Eating out" in budgetable


# --- the budgets screen and the dotted line ------------------------------------------


def test_budgets_show_the_net_spend(w):
    """AC-1."""
    w.dinner_example("spend")
    w.budget("Eating out", 150)
    spend = w.spend_in()
    assert (spend.by_category, spend.gross_by_category) == ({"Eating out": Decimal("90.00")},
                                                            {"Eating out": Decimal("200.00")})
    body = w.get().json()
    [budget] = body["budgets"]
    assert Decimal(budget["spent"]) == Decimal("90.00") and budget["status"] != "over"
    paid = body["not_counted"]
    assert Decimal(paid["paid_back"]) == Decimal("110.00")
    assert [(m["label"], Decimal(m["amount"]), m["against"]) for m in paid["paid_back_marks"]] == [
        ("Sam £60, Pizza Express", Decimal("60.00"), "Pizza Express"),
        ("Jo £50, Pizza Express", Decimal("50.00"), "Pizza Express"),
    ]
    assert Decimal(body["summary_this_cycle"]["left"]) == Decimal("60.00")


def test_a_category_nets_to_zero_at_most_and_the_excess_is_never_income(w):
    """AC-4: £40 marked to Eating out in a cycle with no Eating-out spending."""
    w.purchase("200.00", days_ago=35)  # last cycle: none this cycle
    w.purchase("12.00", category="Groceries", merchant="Tesco")
    w.budget("Eating out", 150)
    w.mark(w.credit("40.00", days_ago=3), "40.00", category="Eating out")
    spend = w.spend_in()
    assert spend.by_category == {"Groceries": Decimal("12.00")}  # no Eating-out line made up
    assert (spend.paid_back, spend.paid_back_excess) == (Decimal("40.00"), {"Eating out": Decimal("40.00")})
    body = w.get().json()
    assert Decimal(body["budgets"][0]["spent"]) == 0
    assert Decimal(body["not_counted"]["paid_back"]) == Decimal("40.00")
    assert [(e["category"], Decimal(e["amount"])) for e in body["not_counted"]["paid_back_excess"]] == [
        ("Eating out", Decimal("40.00"))]
    assert Decimal(body["total_spent"]) == Decimal("12.00")  # not £12 - £40


def test_marking_raises_left_and_lowers_only_the_dotted_line(w):
    """AC-6: with the £110 already landed, marking it raises `left` from £0
    to £60, so the strip's after-budgets balance falls £60; the solid line
    doesn't move."""
    dinner, sam, jo = w.purchase("200.00"), w.credit("60.00"), w.credit("50.00", days_ago=10, merchant="JO")
    w.budget("Eating out", 150)

    def forecast():
        r = w.client.get(f"{API}/analytics/forecast", params={"horizon": "payday"}, headers=_bearer(w.web))
        assert r.status_code == 200, r.text
        return r.json()

    before = forecast()
    w.mark(sam, "60.00", spend=dinner)
    w.mark(jo, "50.00", spend=dinner)
    after = forecast()

    assert Decimal(w.get().json()["summary_this_cycle"]["left"]) == Decimal("60.00")
    assert (Decimal(before["budget_projection"]["after_budgets_balance"])
            - Decimal(after["budget_projection"]["after_budgets_balance"])) == Decimal("60.00")
    assert after["timeline"] == before["timeline"]
