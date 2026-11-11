"""Paid-back marks on the transaction list and search (T-03-3 P6; PRD AC-24,
data for ACs 29-32; T-03-2 section 5).

Both payments of a mark show it: a debit carries `paid_back_amount` (what
its marks net) and both sides list `paid_back_marks`, each with its amount,
target, label, who made it, whether it applies now (a spend no longer counted
as spending nets nothing, AC-29) and whether its cycle has closed. A mark
Claude made carries the audit id the app's Undo needs. Search's
`total_amount` stays the bank total: marks never change it.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import RepaymentMark
from tests.clock import TODAY
from tests.integration.test_oauth import _bearer
from tests.integration.test_repayment_mark_api import World
from tests.integration.test_transactions_endpoint import _tx

LIST = "/api/v1/banking/transactions"
SEARCH = "/api/v1/banking/transactions/search"


class Ledger(World):
    def items(self, token=None, **params):
        r = self.client.get(LIST, params={"page_size": 100, **params}, headers=_bearer(token or self.web))
        assert r.status_code == 200, r.text
        return {i["id"]: i for i in r.json()["items"]}

    def tx_id(self, tx) -> str:
        return str(self.ledger.as_user(lambda: tx.id))

    def recent(self, amount, ttype="debit", merchant="Pizza Express"):
        return self.ledger.as_user(lambda: _tx(self.db, self.ledger.account, amount, TODAY - timedelta(days=3),
                                               ttype=ttype, merchant=merchant, category="Eating out"))


@pytest.fixture
def w(client, db_session):
    return Ledger(client, db_session)


def test_without_marks_debits_show_nothing_paid_back(w):
    items = w.items()
    assert items[w.tx_id(w.dinner)]["paid_back_amount"] == "0.00"
    assert items[w.tx_id(w.sam)]["paid_back_amount"] is None
    assert all(i["paid_back_marks"] == [] for i in items.values())


def test_a_claude_mark_shows_on_both_payments(w):
    applied = w.post([w.entry(spend=w.dinner)], dry_run=False).json()
    items = w.items()

    dinner, sam = items[w.tx_id(w.dinner)], items[w.tx_id(w.sam)]
    assert dinner["paid_back_amount"] == "60.00"
    [mark] = dinner["paid_back_marks"]
    assert sam["paid_back_marks"] == [mark]
    assert mark == {
        "mark_id": applied["results"][0]["target_id"], "credit_id": w.tx_id(w.sam), "spend_id": w.tx_id(w.dinner),
        "category": None, "amount": "60.00", "label": "SAM £60.00, Acme", "created_via": "mcp",
        "applied": True, "cycle_closed": True, "audit_id": applied["results"][0]["audit_id"],
    }


def test_a_category_mark_shows_on_the_credit_only_and_an_open_cycle_is_not_closed(w):
    jo = w.recent("50.00", ttype="credit", merchant="JO")
    w.post([w.entry(credit=jo, category="Eating out")], dry_run=False)
    items = w.items()
    [mark] = items[w.tx_id(jo)]["paid_back_marks"]
    assert (mark["category"], mark["spend_id"], mark["cycle_closed"]) == ("Eating out", None, False)
    assert items[w.tx_id(w.dinner)]["paid_back_marks"] == []


def test_a_spend_no_longer_counted_shows_its_mark_as_not_applied(w):
    w.post([w.entry(spend=w.dinner)], dry_run=False)
    w.ledger.as_user(lambda: (setattr(w.dinner, "counts_as_override", "transfer"), w.db.commit()))
    items = w.items()
    assert items[w.tx_id(w.dinner)]["paid_back_amount"] == "0.00"
    assert items[w.tx_id(w.sam)]["paid_back_marks"][0]["applied"] is False


def test_unmarked_and_other_users_marks_never_show(client, db_session):
    w = Ledger(client, db_session)
    w.ledger.mark(w.sam, "60.00", spend=w.dinner, active=False)
    other = Ledger(client, db_session, email="other@example.com")
    other.ledger.mark(other.sam, "60.00", spend=other.dinner)
    assert all(i["paid_back_marks"] == [] for i in w.items().values())


def test_search_carries_the_marks_and_its_total_stays_the_bank_total(w):
    def search():
        r = w.client.post(SEARCH, json={"query": "acme", "frm": "2026-09-01"}, headers=_bearer(w.mcp))
        assert r.status_code == 200, r.text
        return r.json()

    before = search()["total_amount"]
    w.post([w.entry(spend=w.dinner)], dry_run=False)
    after = search()
    assert after["total_amount"] == before
    assert after["items"][0]["paid_back_amount"] == "60.00" and after["items"][0]["paid_back_marks"]


def test_a_mark_made_in_the_app_has_no_audit_id(w):
    w.ledger.mark(w.sam, "60.00", spend=w.dinner)
    w.ledger.as_user(lambda: (w.db.query(RepaymentMark).update({"created_via": "web"}), w.db.commit()))
    [mark] = w.items()[w.tx_id(w.dinner)]["paid_back_marks"]
    assert mark["created_via"] == "web" and mark["audit_id"] is None
    assert Decimal(mark["amount"]) == Decimal("60.00")
