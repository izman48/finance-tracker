"""A holding's contribution changes only through the holding (T-11-3b; sec
T-11-3, checklist section 9 "Generalising a guarded mechanism").

The Sprint 10 guards key off `linked_commitment_ids()`, which now reads the
shared link set. One test per caller, for a contribution link, using
`test_linked_commitment_guards.py` as the template: web PATCH, skip and
mark-as-recurring; Claude's update, dismiss and undo; detection; the list;
`link_card_commitments`; `_card_ties`. Synthetic: £500 a month into an ISA.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import AuditEntry, CommitmentRule, Transaction
from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_commitment_links import Links
from tests.integration.test_linked_commitment_guards import API, _bearer
from tests.integration.test_transactions_endpoint import _account

HOLDING = {"code": "linked_to_holding",
           "message": "This payment follows your investment. Change it on Wealth, under Investments."}


@pytest.fixture
def world(client, db_session):
    return Links(client, db_session, email="contribution-guards@example.com")


def _with_current_account(world, balance="5000"):
    with world.as_user():
        return _account(world.db, world.user.id, name="Current", balance=balance)


# --------------------------------------------------------------------------- #
# The user's own edits
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("change", [
    {"amount": "450.00"},
    {"card_account_id": "CARD"},
    {"cadence": "weekly"},
    {"interval_days": 14},
    {"next_date": (TODAY + timedelta(days=20)).isoformat()},
    {"status": "dismissed"},
])
def test_a_web_edit_of_a_contribution_is_409_and_writes_nothing(world, change):
    bill = world.contribution()
    if change.get("card_account_id") == "CARD":
        change = {"card_account_id": str(world.amex_card())}
    before = world.snapshot(bill)
    res = world.patch(bill, **change)
    assert res.status_code == 409
    assert res.json()["detail"] == HOLDING
    assert world.snapshot(bill) == before


def test_renaming_a_contribution_is_allowed(world):
    bill = world.contribution()
    assert world.patch(bill, label="ISA top-up").status_code == 200


def test_skipping_a_contribution_is_409(world):
    bill = world.contribution()
    before = world.snapshot(bill)
    res = world.client.post(f"{API}/analytics/commitments/{bill}/skip", headers=_bearer(world.web))
    assert res.status_code == 409
    assert res.json()["detail"] == HOLDING
    assert world.snapshot(bill) == before


def test_marking_a_payment_recurring_cannot_rewrite_a_contribution(world):
    asset_id = world.asset()
    bill = world.commitment(label="ISA DD", amount="500.00", match_key="expense:isa dd")
    world.link(bill, asset_id)
    before = world.snapshot(bill)
    with world.as_user():
        account = _account(world.db, world.user.id, name="Current")
        tx = Transaction(account_id=account.id, external_id="tx-isa-1", transaction_type="debit",
                         amount=Decimal("520.00"), description="ISA DD",
                         transaction_date=datetime.now(timezone.utc) - timedelta(days=2))
        world.db.add(tx)
        world.db.commit()
        tx_id = str(tx.id)
    res = world.client.post(f"{API}/analytics/commitments/from-transaction",
                            json={"transaction_id": tx_id, "cadence": "weekly"}, headers=_bearer(world.web))
    assert res.status_code == 409
    assert res.json()["detail"] == HOLDING
    assert world.snapshot(bill) == before


# --------------------------------------------------------------------------- #
# Claude's edits
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("change", [
    {"amount": "450.00"},
    {"cadence": "weekly"},
    {"next_date": (TODAY + timedelta(days=20)).isoformat()},
    {"status": "confirmed"},
    {"card_account_id": "CARD"},
])
@pytest.mark.parametrize("dry_run", [True, False])
def test_claude_cannot_change_a_contribution(world, change, dry_run):
    bill = world.contribution()
    if change.get("card_account_id") == "CARD":
        change = {"card_account_id": str(world.amex_card())}
    before, audits = world.snapshot(bill), world.audit_count()
    res = world.update(bill, dry_run=dry_run, **change)
    assert res.status_code == 409
    assert res.json()["detail"] == HOLDING
    assert world.snapshot(bill) == before
    assert world.audit_count() == audits


@pytest.mark.parametrize("dry_run", [True, False])
def test_claude_cannot_dismiss_a_contribution_to_raise_safe_to_spend(world, dry_run):
    _with_current_account(world)
    bill = world.contribution()
    safe, audits = world.summary()["safe_to_spend"], world.audit_count()
    res = world.dismiss(bill, dry_run=dry_run)
    assert res.status_code == 409
    assert world.rule(bill).status == "confirmed"
    assert world.summary()["safe_to_spend"] == safe
    assert world.audit_count() == audits


def test_undoing_an_earlier_claude_change_cannot_rewrite_a_contribution(world):
    bill = world.commitment(label="ISA DD", amount="400.00")
    assert world.update(bill, dry_run=False, amount="500.00").status_code == 200
    world.link(bill, world.asset())
    audit_id = world.db.query(AuditEntry.id).filter(AuditEntry.target_id == bill).scalar()
    res = world.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(world.web))
    assert res.status_code == 409
    assert world.rule(bill).amount == Decimal("500.00")


# --------------------------------------------------------------------------- #
# Detection, the list, and cards
# --------------------------------------------------------------------------- #
def test_detection_never_suggests_a_contributions_payments_again(world):
    bill = world.contribution()
    payment_day = world.rule(bill).next_date
    with world.as_user():
        account = _account(world.db, world.user.id, name="Current")
        for n, months_back in enumerate((3, 2, 1)):
            when = _add_months(payment_day, -months_back)
            for ref, amount, text in (("isa", "500.00", "EXAMPLE ISA PROVIDER"), ("gym", "30.00", "GYM LTD")):
                world.db.add(Transaction(
                    account_id=account.id, external_id=f"tx-{ref}-{n}", transaction_type="debit",
                    amount=Decimal(amount), description=text,
                    transaction_date=datetime(when.year, when.month, when.day, tzinfo=timezone.utc),
                ))
        world.db.commit()
    rules = world.client.get(f"{API}/analytics/commitments", headers=_bearer(world.web)).json()
    assert [r["label"] for r in rules if r["status"] == "suggested"] == ["GYM LTD"]


def test_a_contribution_is_listed_as_a_holding_link_not_a_loan(world):
    bill = world.contribution()
    loan_bill = world.linked_bill()
    rows = {r["id"]: r for r in world.client.get(f"{API}/analytics/commitments", headers=_bearer(world.web)).json()}
    assert (rows[str(bill)]["linked_holding"], rows[str(bill)]["linked_liability"]) == (True, False)
    assert (rows[str(loan_bill)]["linked_holding"], rows[str(loan_bill)]["linked_liability"]) == (False, True)


def test_a_contribution_named_after_a_card_is_never_tied_to_it(world):
    # "AMEX ISA" starts with a card descriptor: link_card_commitments must
    # skip it, or the card's repayment would replace it in safe-to-spend.
    world.amex_card(owed="1500.00")
    _with_current_account(world)
    before = world.summary()
    bill = world.contribution(label="American Express ISA")
    after = world.summary()
    assert world.rule(bill).card_account_id is None
    assert Decimal(after["committed_before_payday"]) - Decimal(before["committed_before_payday"]) == Decimal("500.00")
    assert Decimal(before["safe_to_spend"]) - Decimal(after["safe_to_spend"]) == Decimal("500.00")


def test_a_contribution_with_a_stored_card_tie_is_still_counted_in_full(world):
    # _card_ties ignores a hand-set tie on a linked bill.
    card_id = world.amex_card(owed="1500.00")
    _with_current_account(world)
    bill = world.contribution()
    before = Decimal(world.summary()["committed_before_payday"])
    with world.as_user():
        rule = world.db.get(CommitmentRule, bill)
        rule.card_account_id, rule.card_link_source = card_id, "user"
        world.db.commit()
    assert Decimal(world.summary()["committed_before_payday"]) == before


def test_the_contribution_is_counted_once_in_the_summary(world):
    _with_current_account(world)
    before = Decimal(world.summary()["committed_before_payday"])
    world.contribution()
    assert Decimal(world.summary()["committed_before_payday"]) - before == Decimal("500.00")
    assert world.db.query(CommitmentRule).filter(CommitmentRule.user_id == world.user.id).count() == 1


def test_an_unlinked_bill_is_edited_as_before(world):
    world.contribution()
    other = world.commitment(label="Gym", amount="30.00")
    assert world.patch(other, amount="35.00").status_code == 200
