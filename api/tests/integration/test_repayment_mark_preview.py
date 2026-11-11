"""What a mark does to the figures, in the preview and the applied result
(T-03-3 P5c; PRD "MCP contract", AC-1, AC-19; T-03-2 decisions T4, T7).

Each mark carries its budget cycle (the spend's, or the credit's for a
category mark), the spend's counted amount, the category's spending and the
budget's left before the call and after it (every mark in the call), and an
`effect` sentence for Claude to read out. "After" uses the same netting rule
as budgets (`budget_spend(extra_marks=)`), so the preview is what will show.
A closed cycle says its result stays as it was (decision 6).
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import Budget
from tests.clock import TODAY
from tests.integration.test_repayment_mark_api import World
from tests.integration.test_transactions_endpoint import _tx


class Example(World):
    """The PRD's dinner in the open cycle: £200 Eating out, a £150 budget,
    Sam £60 and Jo £50 a few days later. No payday, so the cycle is the last
    30 days."""

    def __init__(self, client, db):
        super().__init__(client, db, email="preview@example.com")
        account = self.ledger.account
        self.pizza = self.ledger.as_user(lambda: _tx(db, account, "200.00", TODAY - timedelta(days=5),
                                                     merchant="Pizza Express", category="Eating out"))
        self.sam2 = self.ledger.as_user(lambda: _tx(db, account, "60.00", TODAY - timedelta(days=3),
                                                    ttype="credit", merchant="SAM"))
        self.jo = self.ledger.as_user(lambda: _tx(db, account, "50.00", TODAY - timedelta(days=2),
                                                  ttype="credit", merchant="JO"))
        self.add(Budget(user_id=self.user.id, category="Eating out", limit_pounds=Decimal("150")))


@pytest.fixture
def ex(client, db_session):
    return Example(client, db_session)


def test_both_marks_show_the_dinner_counting_as_90_and_60_left(ex):
    r = ex.post([ex.entry(credit=ex.sam2, spend=ex.pizza), ex.entry(credit=ex.jo, spend=ex.pizza)])
    assert r.status_code == 200, r.text
    first = r.json()["marks"][0]
    assert first["cycle"] == {"start": (TODAY - timedelta(days=29)).isoformat(), "end": TODAY.isoformat(),
                              "closed": False}
    assert (first["spend_before"], first["spend_after"]) == ("200.00", "90.00")
    assert (first["category_spent_before"], first["category_spent_after"]) == ("200.00", "90.00")
    assert (first["budget_left_before"], first["budget_left_after"]) == ("-50.00", "60.00")
    assert first["effect"] == "Pizza Express: £200.00 counts as £90.00 in Eating out. £60.00 left of £150.00."


def test_a_category_mark_has_no_spend_figures_and_no_budget_is_null(ex):
    r = ex.post([ex.entry(credit=ex.jo, category="Eating out"), ex.entry(credit=ex.sam2, category="Groceries")])
    assert r.status_code == 422  # Groceries isn't a category of theirs; a real one below
    r = ex.post([ex.entry(credit=ex.jo, category="Eating out")])
    mark = r.json()["marks"][0]
    assert mark["spend_before"] is None and mark["spend_after"] is None
    assert (mark["category_spent_before"], mark["category_spent_after"]) == ("200.00", "150.00")
    assert mark["effect"] == "Eating out: £200.00 counts as £150.00. £0.00 left of £150.00."


def test_no_budget_means_null_budget_figures(ex):
    lunch = ex.ledger.as_user(lambda: _tx(ex.db, ex.ledger.account, "30.00", TODAY - timedelta(days=4),
                                          merchant="Cafe", category="Coffee"))
    mark = ex.post([ex.entry(credit=ex.jo, spend=lunch)]).json()["marks"][0]
    assert mark["budget_left_before"] is None and mark["budget_left_after"] is None
    assert mark["effect"] == "Cafe: £30.00 counts as £0.00 in Coffee."


def test_a_spend_in_a_closed_cycle_says_its_result_stays(ex):
    mark = ex.post([ex.entry(spend=ex.dinner)]).json()["marks"][0]  # Ledger's dinner, weeks ago
    assert mark["cycle"]["closed"] is True
    assert mark["effect"].endswith("That cycle has closed, so its result stays as it was.")


def test_the_applied_result_carries_the_same_figures_and_a_replay_does_not(ex):
    body = {"dry_run": False, "idempotency_key": "preview-key-1"}
    applied = ex.post([ex.entry(credit=ex.sam2, spend=ex.pizza)], **body).json()
    assert applied["marks"][0]["spend_after"] == "140.00" and applied["results"][0]["audit_id"]
    replay = ex.post([ex.entry(credit=ex.sam2, spend=ex.pizza)], **body).json()
    assert "marks" not in replay and replay["results"] == applied["results"]
