"""A planned event drops out once its real transaction lands (T-08-7).

Matching runs at request time with the user's key (amounts and descriptions
are encrypted) and is recomputed on every read, so it is reversible: delete
the transaction, or mark it a transfer, and the event comes back.

A one-off planned item is matched by a transaction that:
  - goes the same way (expense <- debit, income <- credit);
  - is within 7 days of the planned date;
  - is within max(GBP 1, 2%) of the planned amount;
  - is not an internal transfer leg, a card repayment, a financed purchase, or
    already a confirmed commitment's payment;
  - hasn't matched another planned item (one-to-one).

Fail safe: an unmatched planned *expense* stays (due now if its date has
passed); an unmatched planned *income* stays expected only until its date + 7
days, then is listed as late and leaves the balance line.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import user_crypto
from app.models import CommitmentRule, PlannedItem, Transaction, User
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_transactions_endpoint import _account, _dek_from_token, _tx

API = "/api/v1"
TODAY = date.today()


class World:
    def __init__(self, client, db, email="match@example.com"):
        self.client, self.db = client, db
        self.web, _, tokens = _connect(client, scopes=(READ,), email=email)
        self.mcp = tokens["access_token"]
        self.dek = _dek_from_token(self.web)
        self.user = db.query(User).filter(User.email == email).one()
        self.current = self.as_user(lambda: _account(db, self.user.id, name="Current", balance="1000.00"))
        self.current_id = self.current.id

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def planned(self, amount, on, direction="expense", name="Planned") -> uuid.UUID:
        def make():
            item = PlannedItem(user_id=self.user.id, name=name, direction=direction, kind="one_off",
                               start_date=on, amount=Decimal(amount), created_via="mcp")
            self.db.add(item)
            self.db.commit()
            return item.id
        return self.as_user(make)

    def tx(self, amount, on, ttype="debit", account=None, merchant="Insurer Ltd") -> uuid.UUID:
        acc = account or self.current
        return self.as_user(lambda: _tx(self.db, acc, amount, on, ttype=ttype, merchant=merchant).id)

    def savings(self):
        return self.as_user(lambda: _account(self.db, self.user.id, atype="SAVINGS", name="Savings", balance="0"))

    def forecast(self):
        res = self.client.get(f"{API}/analytics/forecast", params={"horizon": "30"}, headers=_bearer(self.web))
        assert res.status_code == 200, res.text
        return res.json()

    def planned_events_in_forecast(self):
        return [e for p in self.forecast()["timeline"] for e in p["events"] if e["kind"] == "planned"]

    def summary(self):
        return self.client.get(f"{API}/analytics/summary", headers=_bearer(self.web)).json()

    def listed(self):
        res = self.client.get(f"{API}/planning/planned-events", headers=_bearer(self.mcp))
        return {i["id"]: i for i in res.json()["items"]}


# --- matching ------------------------------------------------------------------------


def test_a_landed_payment_drops_the_planned_expense_and_is_counted_once(client, db_session):
    w = World(client, db_session)
    item = w.planned("200.00", TODAY + timedelta(days=3))
    before = w.summary()
    assert len(w.planned_events_in_forecast()) == 1

    tx = w.tx("200.00", TODAY)  # paid early, inside the window
    assert w.planned_events_in_forecast() == []
    assert Decimal(w.summary()["committed_before_payday"]) == Decimal(before["committed_before_payday"]) - 200
    assert w.listed()[str(item)]["matched_transaction_id"] == str(tx)


@pytest.mark.parametrize("planned,paid,matches", [
    ("100.00", "102.00", True),    # 2% of 100 = 2.00 (more than GBP 1)
    ("100.00", "102.01", False),
    ("100.00", "98.00", True),
    ("100.00", "97.99", False),
    ("20.00", "21.00", True),      # GBP 1 floor (2% would be 0.40)
    ("20.00", "21.01", False),
])
def test_amount_tolerance_is_max_of_one_pound_and_two_percent(client, db_session, planned, paid, matches):
    w = World(client, db_session)
    item = w.planned(planned, TODAY)
    w.tx(paid, TODAY)
    assert (w.listed()[str(item)]["matched_transaction_id"] is not None) is matches


@pytest.mark.parametrize("days,matches", [(7, True), (-7, True), (8, False), (-8, False)])
def test_date_window_is_seven_days(client, db_session, days, matches):
    w = World(client, db_session)
    planned_on = TODAY - timedelta(days=8)
    item = w.planned("50.00", planned_on)
    w.tx("50.00", min(planned_on + timedelta(days=days), TODAY))
    assert (w.listed()[str(item)]["matched_transaction_id"] is not None) is matches


def test_a_credit_never_settles_a_planned_expense(client, db_session):
    w = World(client, db_session)
    item = w.planned("75.00", TODAY)
    w.tx("75.00", TODAY, ttype="credit")
    assert w.listed()[str(item)]["matched_transaction_id"] is None


def test_a_transfer_to_own_savings_does_not_pay_a_planned_expense(client, db_session):
    """Moving GBP 500 to savings on the due date must leave the GBP 500 bill in
    the forecast; otherwise outgoings would be understated."""
    w = World(client, db_session)
    savings = w.savings()
    due = TODAY + timedelta(days=2)
    item = w.planned("500.00", due)
    w.tx("500.00", TODAY, ttype="debit", merchant="To savings")
    w.tx("500.00", TODAY, ttype="credit", account=savings, merchant="From current")
    assert w.listed()[str(item)]["matched_transaction_id"] is None
    assert [e["amount"] for e in w.planned_events_in_forecast()] == ["-500.00"]


def test_a_card_repayment_does_not_pay_a_planned_expense(client, db_session):
    w = World(client, db_session)
    item = w.planned("300.00", TODAY)
    w.tx("300.00", TODAY, merchant="AMEX PAYMENT")
    assert w.listed()[str(item)]["matched_transaction_id"] is None


def test_a_payment_already_settling_a_commitment_is_not_reused(client, db_session):
    w = World(client, db_session)
    w.as_user(lambda: (db_session.add(CommitmentRule(
        user_id=w.user.id, direction="expense", label="Gym Co", amount=Decimal("40"), cadence="monthly",
        next_date=TODAY + timedelta(days=30), source="manual", status="confirmed",
        match_key="expense:gym co")), db_session.commit()))
    item = w.planned("40.00", TODAY)
    w.tx("40.00", TODAY, merchant="Gym Co")
    assert w.listed()[str(item)]["matched_transaction_id"] is None


def test_one_payment_matches_one_planned_event(client, db_session):
    w = World(client, db_session)
    a = w.planned("50.00", TODAY + timedelta(days=1), name="A")
    b = w.planned("50.00", TODAY + timedelta(days=2), name="B")
    w.tx("50.00", TODAY)
    listed = w.listed()
    matched = [i for i in (a, b) if listed[str(i)]["matched_transaction_id"]]
    assert len(matched) == 1
    assert [e["amount"] for e in w.planned_events_in_forecast()] == ["-50.00"]


# --- reversible ----------------------------------------------------------------------


def test_deleting_the_transaction_brings_the_event_back(client, db_session):
    w = World(client, db_session)
    item = w.planned("200.00", TODAY + timedelta(days=1))
    tx = w.tx("200.00", TODAY)
    assert w.planned_events_in_forecast() == []
    db_session.execute(text("DELETE FROM transactions WHERE id = :id"), {"id": tx.hex})
    db_session.commit()
    assert w.listed()[str(item)]["matched_transaction_id"] is None
    assert len(w.planned_events_in_forecast()) == 1


def test_marking_the_transaction_a_transfer_brings_the_event_back(client, db_session):
    w = World(client, db_session)
    item = w.planned("200.00", TODAY + timedelta(days=1))
    tx = w.tx("200.00", TODAY)
    assert w.listed()[str(item)]["matched_transaction_id"] == str(tx)
    def mark():
        db_session.get(Transaction, tx).counts_as_override = "transfer"
        db_session.commit()
    w.as_user(mark)
    assert w.listed()[str(item)]["matched_transaction_id"] is None


# --- unmatched: fail safe ----------------------------------------------------------


def test_an_overdue_unpaid_expense_is_still_due(client, db_session):
    w = World(client, db_session)
    before = Decimal(w.summary()["safe_to_spend"])
    w.planned("120.00", TODAY - timedelta(days=5))
    assert Decimal(w.summary()["safe_to_spend"]) == before - 120
    assert [e["amount"] for e in w.planned_events_in_forecast()] == ["-120.00"]


def test_expected_income_stays_until_seven_days_late_then_is_flagged_not_counted(client, db_session):
    w = World(client, db_session)
    recent = w.planned("400.00", TODAY - timedelta(days=3), direction="income", name="Refund A")
    late = w.planned("900.00", TODAY - timedelta(days=8), direction="income", name="Refund B")
    forecast = w.forecast()
    labels = [e["label"] for p in forecast["timeline"] for e in p["events"]]
    assert "Refund A" in labels and "Refund B" not in labels
    assert [(i["label"], i["amount"], i["expected_date"]) for i in forecast["late_planned"]] == [
        ("Refund B", "900.00", (TODAY - timedelta(days=8)).isoformat())
    ]
    listed = w.listed()
    assert listed[str(recent)]["late"] is False and listed[str(late)]["late"] is True


def test_income_that_lands_clears_it(client, db_session):
    w = World(client, db_session)
    item = w.planned("900.00", TODAY - timedelta(days=8), direction="income", name="Refund B")
    w.tx("900.00", TODAY - timedelta(days=2), ttype="credit", merchant="Shop refund")
    forecast = w.forecast()
    assert forecast["late_planned"] == []
    assert w.listed()[str(item)]["late"] is False
    assert w.listed()[str(item)]["matched_transaction_id"] is not None
