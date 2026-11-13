"""Commitments inside their budget category (T-24-3a; sec's T-24-3 criteria).

A commitment's payment counts in its category's budget when that category
has an active, unpaused budget, only once it is paid. With no budget on its
category it stays under "Not counted here" as before. Synthetic merchants
and amounts only.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import CommitmentRule
from tests.clock import TODAY
from tests.integration.test_budgets_api import World
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _tx

KIT = "MEAL KIT CO"


def _weekly(w, label=KIT, amount="16.00", category="Eating out", paid_days_ago=(5, 12, 19), next_in=2):
    """A weekly commitment and its payments (category as the bank gave it)."""
    def make():
        for days in paid_days_ago:
            _tx(w.db, w.current, amount, TODAY - timedelta(days=days), merchant=label, category=category)
        rule = CommitmentRule(user_id=w.user.id, direction="expense", label=label, amount=Decimal(amount),
                              cadence="weekly", next_date=TODAY + timedelta(days=next_in),
                              source="manual", status="confirmed")
        w.db.add(rule)
        w.db.commit()
        return rule.id
    return w.as_user(make)


def _budgets(w) -> dict:
    return w.client.get("/api/v1/budgets", headers=_bearer(w.web)).json()


def _row(w, category="Eating out"):
    body = _budgets(w)
    return body, next(b for b in body["budgets"] if b["category"] == category)


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.history()  # Eating out £40 this cycle; rent £950 (category Rent), next due in 5 days
    return world


def test_paid_instalments_count_in_the_budget(w):
    _weekly(w)
    w.create("Eating out", 150)
    body, row = _row(w)
    assert Decimal(row["spent"]) == Decimal("88.00")  # £40 purchases + 3 x £16 paid
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("950.00")  # rent: no budget


def test_with_no_budget_on_its_category_a_commitment_stays_not_counted(w):
    _weekly(w)
    w.create("Groceries", 300)
    body, _ = _row(w, "Groceries")
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("998.00")  # rent + 3 x £16, as today
    assert Decimal(body["other_spending"]) == Decimal("160.00")  # Eating out £40 + Shopping £120, no kit


def test_a_paused_budget_counts_no_commitment(w):
    _weekly(w)
    budget_id = w.create("Eating out", 150).json()["id"]
    w.patch(budget_id, paused=True)
    body, row = _row(w)
    assert Decimal(row["spent"]) == Decimal("40.00")
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("998.00")


def test_spent_exactly_at_the_limit_is_budget_used(w):
    _weekly(w)
    w.create("Eating out", 88)
    _, row = _row(w)
    assert row["status"] == "budget_used"
    w.create("Groceries", 300)
    assert _row(w, "Groceries")[1]["status"] != "budget_used"


def test_a_zero_amount_rules_payments_count(w):
    """B-34: a key-only £0 rule in a budgeted category hides nothing."""
    _weekly(w, label="VEG BOX", amount="0.00", paid_days_ago=())
    w.as_user(lambda: _tx(w.db, w.current, "9.00", TODAY - timedelta(days=3), merchant="VEG BOX",
                          category="Eating out"))
    w.create("Eating out", 150)
    _, row = _row(w)
    assert Decimal(row["spent"]) == Decimal("49.00")  # £40 + the £9 VEG BOX payment


def test_another_users_commitments_never_count(client, db_session):
    a = World(client, db_session, email="a@example.com")
    a.history()
    b = World(client, db_session, email="b@example.com")
    b.history()
    _weekly(b)
    _weekly(a, amount="7.00")
    a.create("Eating out", 150)
    _, row = _row(a)
    assert Decimal(row["spent"]) == Decimal("61.00")  # £40 + 3 x £7


def test_a_budget_can_be_set_on_a_category_that_is_mostly_commitments(w):
    """The covered-category block is lifted; safe to spend and the forecast
    don't move when it is."""
    def figures():
        s = w.client.get("/api/v1/analytics/summary", headers=_bearer(w.web)).json()
        f = w.client.get("/api/v1/analytics/forecast", headers=_bearer(w.web)).json()
        return s["safe_to_spend"], s["savable"], f["end_balance"], f["min_balance"]
    before = figures()
    assert w.create("Rent", 1000).status_code == 201
    _, row = _row(w, "Rent")
    assert Decimal(row["spent"]) == Decimal("950.00")
    assert figures() == before


def test_a_bill_claude_confirms_without_a_keep_moves_no_spending_out(client, db_session):
    """B-26 not made worse: in a budgeted category a commitment's payment
    counts either way, so Claude confirming one hides nothing."""
    from tests.integration.test_no_claude_raise import World as BillWorld
    from tests.integration.test_transactions_endpoint import _account

    bill = BillWorld(client, db_session, email="claude-confirms@example.com")

    def suggested():
        _tx(db_session, _account(db_session, bill.user.id, name="Current", balance="900"), "45.00",
            TODAY - timedelta(days=2), merchant="TOP UP CO", category="Phone")
        rule = CommitmentRule(user_id=bill.user.id, direction="expense", label="TOP UP CO", amount=Decimal("45"),
                              cadence="monthly", next_date=TODAY + timedelta(days=28), source="detected",
                              status="suggested")
        db_session.add(rule)
        db_session.commit()
        return rule.id
    rule_id = bill.as_user(suggested)
    r = client.post("/api/v1/budgets", json={"category": "Phone", "limit_pounds": 400}, headers=_bearer(bill.web))
    assert r.status_code == 201, r.text
    bill.claude_update(rule_id, status="confirmed")
    assert _row(bill, "Phone")[1]["spent"] == "45.00"


def test_suggest_measures_a_commitment_the_way_the_budget_counts_it(w):
    """eng-b on #294: Suggest and Past cycles must agree on a cycle's spend,
    so a category's paid commitments are in its suggested figures too."""
    def last_cycles():
        rows = w.suggest().json()["suggestions"]
        return [Decimal(c["spent"]) for c in next(s for s in rows if s["category"] == "Eating out")["last_cycles"]]
    before = last_cycles()
    _weekly(w, amount="5.00", paid_days_ago=(26, 33, 40))  # three instalments in the last complete cycle
    after = last_cycles()
    assert after[-1] == before[-1] + Decimal("15.00")
    assert after[:-1] == before[:-1]
