"""A liability's repayment is one linked commitment (T-10-8a; spec stage 2;
sec T-10-8; ux A5-A7; owner D4).

Rules (spec):
1. A liability with a fixed payment creates a linked commitment.
2. An existing commitment with the same amount and cadence is linked, not
   duplicated. More than one: 409 `choose_commitment`; the client resends a
   candidate id or "new", and the server re-computes the candidates.
3. Opting out removes the link and the commitment, in one transaction.
4. Editing the payment or cadence updates the commitment.
5. The commitment ends after the final scheduled payment (paid off).
6. Revolving balances never create one (not a liability kind).

The link is the stored `linked_commitment_id`, never label matching. While
linked, today's balance follows the schedule (payments are in the forecast);
unlinked, it is the entered balance. Deleting a liability without opting out
keeps the commitment as an ordinary bill (D4). Synthetic fixture: £9,000 at
£200 a month, 11% APR (hand-checked schedule in test_amortisation.py).
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core import user_crypto
from app.models import CommitmentRule, Liability, User
from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_oauth import _bearer, _web_login
from tests.integration.test_transactions_endpoint import _dek_from_token

API = "/api/v1"
# The next payment, kept on a day every month has, so month steps are exact.
NEXT = min(TODAY + timedelta(days=5), (TODAY + timedelta(days=5)).replace(day=28))
START = _add_months(NEXT, -2)  # two payments already made
AS_OF = START - timedelta(days=3)


def loan(**overrides) -> dict:
    body = {
        "kind": "loan", "lender": "Example Bank", "balance": "9000.00", "balance_as_of": AS_OF.isoformat(),
        "apr": "11.00", "payment": "200.00", "start_date": START.isoformat(),
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None}


class Person:
    def __init__(self, client, db, email):
        self.client, self.db = client, db
        self.token = _web_login(client, email)
        self.user = db.query(User).filter(User.email == email).one()
        self.dek = _dek_from_token(self.token)

    def as_user(self, fn):
        """Direct DB access under this user's key (requests carry their own)."""
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def create(self, **overrides):
        return self.client.post(f"{API}/liabilities", json=loan(**overrides), headers=_bearer(self.token))

    def patch(self, liability_id, **body):
        return self.client.patch(f"{API}/liabilities/{liability_id}", json=body, headers=_bearer(self.token))

    def delete(self, liability_id):
        return self.client.delete(f"{API}/liabilities/{liability_id}", headers=_bearer(self.token))

    def bill(self, label="LOAN DD", amount="200.00", cadence="monthly", status="confirmed", **extra) -> str:
        def make():
            rule = CommitmentRule(
                user_id=self.user.id, direction="expense", label=label, amount=Decimal(amount), cadence=cadence,
                next_date=TODAY + timedelta(days=9), source="manual", status=status, **extra,
            )
            self.db.add(rule)
            self.db.commit()
            return str(rule.id)
        return self.as_user(make)

    def bills(self) -> list[CommitmentRule]:
        """Loaded and read under the user's key (amounts and labels are encrypted)."""
        def load():
            self.db.expire_all()
            rules = self.db.query(CommitmentRule).filter(CommitmentRule.user_id == self.user.id).all()
            for r in rules:
                _ = (r.label, r.amount)  # decrypt while the key is set
            return rules
        return self.as_user(load)

    def forecast_payments(self, label="Example Bank") -> list[str]:
        f = self.client.get(f"{API}/analytics/forecast?horizon=90", headers=_bearer(self.token)).json()
        return [p["date"] for p in f["timeline"] for e in p["events"] if e["label"] == label]


@pytest.fixture
def alice(client, db_session):
    return Person(client, db_session, "alice-link@example.com")


@pytest.fixture
def bob(client, db_session):
    return Person(client, db_session, "bob-link@example.com")


def _set_card_link(person, rule_id):
    """Mark the bill as a card repayment (test SQLite doesn't enforce the FK)."""
    rule = person.db.get(CommitmentRule, uuid.UUID(rule_id))
    rule.card_account_id = uuid.uuid4()
    rule.card_link_source = "user"
    person.db.commit()


def _liabilities(db) -> int:
    return len(db.execute(select(Liability.id)).all())


# --------------------------------------------------------------------------- #
# Rule 1: a fixed payment creates a linked commitment
# --------------------------------------------------------------------------- #
def test_liability_creates_commitment_by_default(alice):
    res = alice.create()
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["link_result"] == "created"
    (bill,) = alice.bills()
    assert body["linked_commitment"] == {"id": str(bill.id), "label": "Example Bank"}
    assert (bill.direction, bill.amount, bill.cadence, bill.status) == ("expense", Decimal("200.00"), "monthly", "confirmed")
    assert bill.next_date == NEXT == date.fromisoformat(body["next_payment_date"])
    assert bill.ends_on == date.fromisoformat(body["payoff_date"])


@pytest.mark.parametrize("cadence, stored", [
    ("weekly", ("weekly", None)), ("fortnightly", ("custom_days", 14)), ("four_weekly", ("custom_days", 28)),
])
def test_the_commitment_follows_the_liabilitys_cadence(alice, cadence, stored):
    assert alice.create(cadence=cadence, payment="100.00").status_code == 201
    (bill,) = alice.bills()
    assert (bill.cadence, bill.interval_days) == stored


def test_an_irregular_liability_creates_no_commitment(alice):
    body = alice.create(payment=None, opted_out=True).json()
    assert body["link_result"] is None and body["linked_commitment"] is None
    assert alice.bills() == []


def test_revolving_balances_never_create_a_commitment(alice, db_session):
    assert alice.create(kind="revolving").status_code == 422
    assert alice.bills() == [] and _liabilities(db_session) == 0


# --------------------------------------------------------------------------- #
# Rule 2: a matching commitment is linked, not duplicated
# --------------------------------------------------------------------------- #
def test_matching_commitment_is_linked_not_duplicated(alice):
    existing = alice.bill()
    body = alice.create().json()
    assert body["link_result"] == "linked"
    assert body["linked_commitment"] == {"id": existing, "label": "LOAN DD"}
    (bill,) = alice.bills()
    assert str(bill.id) == existing
    assert bill.next_date == NEXT  # the liability's schedule now drives it


def test_a_suggested_match_is_confirmed_when_linked(alice):
    alice.bill(status="suggested")
    assert alice.create().json()["link_result"] == "linked"
    (bill,) = alice.bills()
    assert bill.status == "confirmed"


def test_dismissed_or_different_commitments_are_not_matches(alice):
    alice.bill(status="dismissed")
    alice.bill(amount="199.99")
    alice.bill(cadence="weekly")
    assert alice.create().json()["link_result"] == "created"
    assert len(alice.bills()) == 4


def test_two_matches_ask_which_bill_and_write_nothing(alice, db_session):
    first, second = alice.bill("LOAN DD"), alice.bill("OTHER DD")
    res = alice.create()
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "choose_commitment"
    assert {c["id"] for c in detail["candidates"]} == {first, second}
    assert set(detail["candidates"][0]) == {"id", "label", "amount", "cadence", "interval_days", "next_date"}
    assert _liabilities(db_session) == 0 and len(alice.bills()) == 2


def test_choosing_a_candidate_links_it(alice):
    first, _ = alice.bill("LOAN DD"), alice.bill("OTHER DD")
    body = alice.create(commitment_choice=first).json()
    assert body["link_result"] == "linked" and body["linked_commitment"]["id"] == first
    assert len(alice.bills()) == 2


def test_choosing_new_adds_a_bill(alice):
    alice.bill("LOAN DD")
    alice.bill("OTHER DD")
    assert alice.create(commitment_choice="new").json()["link_result"] == "created"
    assert len(alice.bills()) == 3


def test_a_choice_outside_the_candidates_gets_a_fresh_list_and_no_write(alice, bob, db_session):
    alice.bill("LOAN DD")
    alice.bill("OTHER DD")
    not_a_match = alice.bill("GYM", amount="30.00")
    bobs = bob.bill("LOAN DD")
    already_linked = alice.bill("THIRD DD")
    # Link THIRD DD to another liability first, so it is no longer a candidate.
    assert alice.create(lender="First", commitment_choice=already_linked).status_code == 201
    before = _liabilities(db_session)

    for choice in (not_a_match, bobs, already_linked, "00000000-0000-0000-0000-0000000000ab", "not-an-id"):
        res = alice.create(commitment_choice=choice)
        assert res.status_code in (409, 422), choice
        if res.status_code == 409:
            assert {c["label"] for c in res.json()["detail"]["candidates"]} == {"LOAN DD", "OTHER DD"}
    assert _liabilities(db_session) == before


def test_a_concurrent_double_link_is_a_409(alice, db_session, monkeypatch):
    taken = alice.bill("LOAN DD")
    assert alice.create(lender="First").json()["linked_commitment"]["id"] == taken
    # Simulate the race: the candidate list was computed before the other
    # request linked the bill, so it still offers it. The unique constraint
    # on linked_commitment_id refuses the second link.
    from app.services import liability_links
    monkeypatch.setattr(liability_links, "_linked_ids", lambda db, user_id: set())
    res = alice.create(lender="Second")
    assert res.status_code == 409
    assert _liabilities(db_session) == 1


# --------------------------------------------------------------------------- #
# Rules 3 and 4: opt out, opt back in, edits
# --------------------------------------------------------------------------- #
def test_opting_out_of_a_taken_over_bill_unlinks_it_and_keeps_it(alice):
    # Rule 3 deletes only a bill the liability created (lead, eng-a on #181):
    # a bill the user already had stays, as an ordinary bill with no end.
    existing = alice.bill()
    created = alice.create().json()
    assert created["link_result"] == "linked"
    body = alice.patch(created["id"], opted_out=True, payment=None).json()
    assert body["linked_commitment"] is None
    (bill,) = alice.bills()
    assert str(bill.id) == existing and bill.status == "confirmed" and bill.ends_on is None


def test_a_card_repayment_commitment_is_never_taken_over(alice):
    card_bill = alice.bill(label="CARD DD")
    alice.as_user(lambda: _set_card_link(alice, card_bill))
    assert alice.create().json()["link_result"] == "created"
    assert len(alice.bills()) == 2


def test_a_dismissed_linked_bill_leaves_the_balance_as_entered(alice):
    created = alice.create().json()
    bill_id = created["linked_commitment"]["id"]

    def dismiss():
        rule = alice.db.get(CommitmentRule, uuid.UUID(bill_id))
        rule.status = "dismissed"  # however it happened, nothing forecasts the payments now
        alice.db.commit()
    alice.as_user(dismiss)
    body = alice.client.get(f"{API}/liabilities/{created['id']}", headers=_bearer(alice.token)).json()
    assert Decimal(body["current_balance"]) == Decimal("9000.00")


def test_opt_out_removes_commitment(alice):
    created = alice.create().json()
    res = alice.patch(created["id"], opted_out=True, payment=None)
    assert res.status_code == 200, res.text
    assert res.json()["linked_commitment"] is None
    assert alice.bills() == []
    assert Decimal(res.json()["current_balance"]) == Decimal("9000.00")  # the entered balance again


def test_opting_back_in_links_again(alice):
    created = alice.create(payment=None, opted_out=True).json()
    body = alice.patch(created["id"], opted_out=False, payment="200.00").json()
    assert body["link_result"] == "created"
    assert len(alice.bills()) == 1


def test_editing_payment_or_cadence_updates_the_commitment(alice):
    created = alice.create().json()
    alice.patch(created["id"], payment="300.00")
    (bill,) = alice.bills()
    assert bill.amount == Decimal("300.00")
    body = alice.patch(created["id"], cadence="fortnightly").json()
    (bill,) = alice.bills()
    assert (bill.cadence, bill.interval_days) == ("custom_days", 14)
    assert bill.next_date == date.fromisoformat(body["next_payment_date"])
    assert bill.ends_on == date.fromisoformat(body["payoff_date"])


def test_deleting_a_liability_keeps_its_bill_as_an_ordinary_one(alice):
    created = alice.create().json()
    assert alice.delete(created["id"]).status_code == 204
    (bill,) = alice.bills()
    assert bill.status == "confirmed" and bill.amount == Decimal("200.00")
    assert bill.ends_on is None  # still forecast: nothing says the loan is gone
    assert alice.forecast_payments()


# --------------------------------------------------------------------------- #
# Balance follows the schedule while linked; rule 5
# --------------------------------------------------------------------------- #
def test_todays_balance_follows_the_schedule_while_linked(alice):
    body = alice.create().json()
    # Two payments since the as-of date: 9,000 → 8,878.61 → 8,756.16.
    assert Decimal(body["current_balance"]) == Decimal("8756.16")
    assert body["payments_remaining"] == 56
    assert Decimal(body["interest_remaining"]) == Decimal("2327.06")
    assert body["payoff_date"] == _add_months(START, 57).isoformat()
    assert body["paid_off"] is False


def test_paid_off_liability_ends_commitment(alice):
    start = _add_months(NEXT, -5)
    body = alice.create(balance="1000.00", apr="0", payment="300.00", start_date=start.isoformat(),
                        balance_as_of=(start - timedelta(days=3)).isoformat()).json()
    assert body["paid_off"] is True
    assert Decimal(body["current_balance"]) == Decimal("0")
    assert body["next_payment_date"] is None and body["payments_remaining"] == 0
    (bill,) = alice.bills()
    assert bill.ends_on == _add_months(start, 3)
    assert alice.forecast_payments() == []


def test_the_last_payment_is_still_forecast_15_days_before_it(alice):
    final = min(TODAY + timedelta(days=15), (TODAY + timedelta(days=15)).replace(day=28))
    start = _add_months(final, -3)
    alice.create(balance="1000.00", apr="0", payment="300.00", start_date=start.isoformat(),
                 balance_as_of=(start - timedelta(days=3)).isoformat())
    assert alice.forecast_payments() == [final.isoformat()]


def test_the_repayment_counts_once_in_summary_forecast_and_projection(alice):
    def figures():
        get = lambda path: alice.client.get(f"{API}{path}", headers=_bearer(alice.token)).json()  # noqa: E731
        forecast = get("/analytics/forecast?horizon=90")
        out = sum(-Decimal(e["amount"]) for p in forecast["timeline"] for e in p["events"] if Decimal(e["amount"]) < 0)
        basis = get("/analytics/net-worth-projection")["contribution_basis"]
        return Decimal(get("/analytics/summary")["committed_before_payday"]), out, Decimal(basis["bills_monthly"])

    committed, forecast_out, bills = figures()
    alice.create()
    after = figures()
    # No payday is set, so the summary window is the next 30 days: one £200.
    assert after[0] - committed == Decimal("200.00")
    # The forecast pays it once per month in 90 days, never twice on a day.
    assert after[1] - forecast_out == Decimal("200.00") * len(alice.forecast_payments())
    assert len(alice.forecast_payments()) == len(set(alice.forecast_payments())) == 3
    # The projection's monthly bills grow by one £200.
    assert after[2] - bills == Decimal("200.00")


def test_renaming_the_lender_renames_a_bill_the_liability_created(alice):
    created = alice.create().json()
    alice.patch(created["id"], lender="Renamed Bank")
    (bill,) = alice.bills()
    assert bill.label == "Renamed Bank"


def test_renaming_the_lender_leaves_a_taken_over_bill_alone(alice):
    alice.bill("LOAN DD")
    created = alice.create().json()
    alice.patch(created["id"], lender="Renamed Bank")
    (bill,) = alice.bills()
    assert bill.label == "LOAN DD"


def test_the_projection_pays_a_linked_debt_down_on_its_schedule(alice):
    alice.create()
    timeline = alice.client.get(f"{API}/analytics/net-worth-projection", headers=_bearer(alice.token)).json()["timeline"]
    # Today 8,756.16 (two payments made); the next payment, within a month,
    # takes it to 8,756.16 + 76.48 - 200 = 8,632.64 (the hand-checked row 3).
    assert Decimal(timeline[0]["liabilities"]) == Decimal("8756.16")
    assert Decimal(timeline[1]["liabilities"]) == Decimal("8632.64")
