"""A planned card payment counts once with the projected card bills
(T-12-4a; owner 2026-10-15: card-agnostic; sec T-12-4).

A planned item can be marked `is_card_payment` (a plain flag, no card is
chosen, never matched by name). In each pay window nilu counts the larger of
the flagged planned card payments and the projected card repayments (all
cards together), never both and never a subtraction: a manual bill larger
than the projection counts in full, and a smaller one gives way to the
projection. Safe-to-spend (summary) and the Cashflow forecast use the same
rule. Claude can't set the flag. Synthetic figures only.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import CommitmentRule
from tests.clock import TODAY
from tests.integration.test_linked_commitment_guards import API, World, _bearer
from tests.integration.test_transactions_endpoint import _account

PAYDAY = TODAY + timedelta(days=12)


class Cards(World):
    def setup(self):
        self.amex_card(owed="640.00")  # a projected £640 repayment a few days ahead
        with self.as_user():
            _account(self.db, self.user.id, name="Current", balance="5000")
            self.db.add(CommitmentRule(user_id=self.user.id, direction="income", label="Salary",
                                       amount=Decimal("3000"), cadence="monthly", next_date=PAYDAY,
                                       source="manual", status="confirmed", is_payday=True))
            self.db.commit()

    def planned(self, amount, days=3, card=True, **extra):
        body = {"name": "Card bill", "direction": "expense", "kind": "one_off",
                "start_date": (TODAY + timedelta(days=days)).isoformat(), "amount": amount,
                "is_card_payment": card, **extra}
        r = self.client.post(f"{API}/analytics/planned-items", json=body, headers=_bearer(self.web))
        assert r.status_code == 201, r.text
        return r.json()

    def committed(self):
        return Decimal(self.summary()["committed_before_payday"])

    def forecast_out_before_payday(self):
        f = self.client.get(f"{API}/analytics/forecast?horizon=payday", headers=_bearer(self.web)).json()
        return -sum((Decimal(str(e["amount"])) for p in f["timeline"] for e in p["events"]
                     if Decimal(str(e["amount"])) < 0), Decimal(0))


@pytest.fixture
def w(client, db_session):
    world = Cards(client, db_session, email="card-payment@example.com")
    world.setup()
    return world


def test_the_baseline_counts_the_projected_bill(w):
    assert w.committed() == Decimal("640.00")
    assert w.forecast_out_before_payday() == Decimal("640.00")


def test_a_larger_planned_card_payment_counts_in_full_and_once(w):
    w.planned("1500.00")
    assert w.committed() == Decimal("1500.00")  # not 2,140
    assert w.forecast_out_before_payday() == Decimal("1500.00")


def test_a_smaller_planned_card_payment_gives_way_to_the_projection(w):
    w.planned("400.00")
    assert w.committed() == Decimal("640.00")  # the larger, never 640 - 400
    assert w.forecast_out_before_payday() == Decimal("640.00")


def test_several_planned_card_payments_are_summed_before_comparing(w):
    w.planned("400.00", days=2)
    w.planned("400.00", days=4)
    assert w.committed() == Decimal("800.00")
    assert w.forecast_out_before_payday() == Decimal("800.00")


def test_an_unflagged_bill_is_never_matched_by_its_name(w):
    w.planned("400.00", card=False)
    assert w.committed() == Decimal("1040.00")  # counted beside the projection


def test_a_card_payment_in_a_window_with_no_projected_bill_still_counts(client, db_session):
    plain = Cards(client, db_session, email="card-payment-plain@example.com")
    with plain.as_user():
        _account(db_session, plain.user.id, name="Current", balance="5000")
        db_session.add(CommitmentRule(user_id=plain.user.id, direction="income", label="Salary",
                                      amount=Decimal("3000"), cadence="monthly", next_date=PAYDAY,
                                      source="manual", status="confirmed", is_payday=True))
        db_session.commit()
    plain.planned("300.00")
    assert plain.committed() == Decimal("300.00")


def test_the_flag_can_be_set_later_by_the_user_only(w, client, db_session):
    item = w.planned("1500.00", card=False)
    assert w.committed() == Decimal("2140.00")
    r = w.client.patch(f"{API}/analytics/planned-items/{item['id']}", json={"is_card_payment": True},
                       headers=_bearer(w.web))
    assert r.status_code == 200 and r.json()["is_card_payment"] is True
    assert w.committed() == Decimal("1500.00")
    other = World(client, db_session, email="card-payment-other@example.com")
    r = other.client.patch(f"{API}/analytics/planned-items/{item['id']}", json={"is_card_payment": False},
                           headers=_bearer(other.web))
    assert r.status_code == 404
    bad = w.client.patch(f"{API}/analytics/planned-items/{item['id']}", json={"amount": "1.00"},
                         headers=_bearer(w.web))
    assert bad.status_code == 422  # only the flag is editable here


def test_claude_cannot_set_the_card_payment_flag(w):
    r = w.client.post(f"{API}/planning/planned-events", headers=_bearer(w.mcp), json={
        "name": "Card bill", "amount": "1500.00", "date": (TODAY + timedelta(days=3)).isoformat(),
        "direction": "expense", "is_card_payment": True, "dry_run": False, "idempotency_key": "card-flag-0001",
    })
    assert r.status_code == 422


def test_claudes_add_request_has_no_card_payment_field():
    from app.schemas import AddPlannedEventRequest
    assert set(AddPlannedEventRequest.model_fields) == {
        "name", "amount", "date", "direction", "account_id", "dry_run", "idempotency_key",
    }
