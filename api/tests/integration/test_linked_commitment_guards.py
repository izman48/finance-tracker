"""A loan's linked commitment can only change through the loan (T-10-8b;
sec T-10-8).

The liability is the source of truth for its repayment. The user's web PATCH
and skip, mark-as-recurring, Claude's `update_commitment` and
`dismiss_commitment`, and undoing an earlier Claude change all return 409
"edit the loan" for amount, cadence, next date and status, and write
nothing. An injected Claude must not be able to dismiss a loan repayment and
raise safe-to-spend. Renaming the bill is still allowed. `sync_suggestions`
never suggests the repayment's payments again, and Claude's summary carries
liabilities only as one total (sec on #177).

Merge together with T-10-8a. Synthetic fixture: £9,000 at £200 a month.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import Account, AccountSetting, AuditEntry, BankConnection, CommitmentRule, Transaction
from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_commitment_writes_api import World as ClaudeWorld
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _account

API = "/api/v1"
NEXT = min(TODAY + timedelta(days=5), (TODAY + timedelta(days=5)).replace(day=28))
LOAN = {
    "kind": "loan", "lender": "Example Bank", "balance": "9000.00",
    "balance_as_of": (TODAY - timedelta(days=3)).isoformat(), "apr": "11.00", "payment": "200.00",
    "start_date": NEXT.isoformat(),
}
LINKED = {"code": "linked_to_liability", "message": "This payment follows your loan. Change it on Wealth, under Loans and finance."}


class World(ClaudeWorld):
    def loan(self, **overrides):
        res = self.client.post(f"{API}/liabilities", json={**LOAN, **overrides}, headers=_bearer(self.web))
        assert res.status_code == 201, res.text
        return res.json()

    def linked_bill(self) -> uuid.UUID:
        return uuid.UUID(self.loan()["linked_commitment"]["id"])

    def patch(self, rule_id, **body):
        return self.client.patch(f"{API}/analytics/commitments/{rule_id}", json=body, headers=_bearer(self.web))

    def summary(self, token=None):
        return self.client.get(f"{API}/analytics/summary", headers=_bearer(token or self.web)).json()

    def snapshot(self, rule_id):
        r = self.rule(rule_id)
        return (r.label, r.amount, r.cadence, r.interval_days, r.next_date, r.status, r.ends_on, r.card_account_id)

    def amex_card(self, owed="1500.00") -> uuid.UUID:
        """An Amex card with a full-balance repayment plan (Amex owed is positive)."""
        with self.as_user():
            conn = BankConnection(user_id=self.user.id, provider_id="ob-amex", provider_name="AMEX",
                                  access_token="t", refresh_token="r")
            self.db.add(conn)
            self.db.flush()
            card = Account(user_id=self.user.id, bank_connection_id=conn.id, external_id=f"amex-{uuid.uuid4()}",
                           provider_name="AMEX", account_type="CREDIT_CARD", display_name="Amex Gold",
                           current_balance=Decimal(owed))
            self.db.add(card)
            self.db.flush()
            self.db.add(AccountSetting(user_id=self.user.id, account_id=card.id, role="credit",
                                       repayment_strategy="full_balance", repayment_cadence="monthly",
                                       repayment_day=NEXT.day))
            card_id = card.id
            self.db.commit()
            return card_id


@pytest.fixture
def world(client, db_session):
    return World(client, db_session, email="guards@example.com")


# --------------------------------------------------------------------------- #
# The user's own edits
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("change", [
    {"amount": "150.00"},
    {"card_account_id": "CARD"},
    {"cadence": "weekly"},
    {"interval_days": 14},
    {"next_date": (TODAY + timedelta(days=20)).isoformat()},
    {"status": "dismissed"},
])
def test_a_web_edit_of_a_linked_commitment_is_409_and_writes_nothing(world, change):
    bill = world.linked_bill()
    if change.get("card_account_id") == "CARD":
        change = {"card_account_id": str(world.amex_card())}
    before = world.snapshot(bill)
    res = world.patch(bill, **change)
    assert res.status_code == 409
    assert res.json()["detail"] == LINKED
    assert world.snapshot(bill) == before


def test_renaming_a_linked_bill_is_allowed(world):
    bill = world.linked_bill()
    assert world.patch(bill, label="Car loan").status_code == 200
    assert world.rule(bill).label == "Car loan"


def test_an_unlinked_commitment_is_edited_as_before(world):
    bill = world.commitment(label="Gym", amount="30.00")
    assert world.patch(bill, amount="35.00").status_code == 200
    assert world.rule(bill).amount == Decimal("35.00")


def test_skipping_a_linked_payment_is_409(world):
    bill = world.linked_bill()
    before = world.snapshot(bill)
    res = world.client.post(f"{API}/analytics/commitments/{bill}/skip", headers=_bearer(world.web))
    assert res.status_code == 409
    assert world.snapshot(bill) == before


def test_marking_a_payment_recurring_cannot_rewrite_a_linked_bill(world):
    bill = world.commitment(label="LOAN DD", amount="200.00", match_key="expense:loan dd")
    assert world.loan()["linked_commitment"]["id"] == str(bill)
    before = world.snapshot(bill)
    with world.as_user():
        account = _account(world.db, world.user.id, name="Current")
        tx = Transaction(
            account_id=account.id, external_id="tx-loan-1", transaction_type="debit", amount=Decimal("210.00"),
            description="LOAN DD", transaction_date=datetime.now(timezone.utc) - timedelta(days=2),
        )
        world.db.add(tx)
        world.db.commit()
        tx_id = str(tx.id)
    res = world.client.post(f"{API}/analytics/commitments/from-transaction",
                            json={"transaction_id": tx_id, "cadence": "weekly"}, headers=_bearer(world.web))
    assert res.status_code == 409
    assert world.snapshot(bill) == before


# --------------------------------------------------------------------------- #
# Claude's edits
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("change", [
    {"amount": "150.00"},
    {"cadence": "weekly"},
    {"next_date": (TODAY + timedelta(days=20)).isoformat()},
    {"status": "confirmed"},
    # sec on #183: tying the loan's bill to a card would let the card's
    # repayment replace it in safe-to-spend.
    {"card_account_id": "CARD"},
])
@pytest.mark.parametrize("dry_run", [True, False])
def test_claude_cannot_change_a_linked_commitment(world, change, dry_run):
    bill = world.linked_bill()
    if change.get("card_account_id") == "CARD":
        change = {"card_account_id": str(world.amex_card())}
    before, audits = world.snapshot(bill), world.audit_count()
    res = world.update(bill, dry_run=dry_run, **change)
    assert res.status_code == 409
    assert res.json()["detail"] == LINKED
    assert world.snapshot(bill) == before
    assert world.audit_count() == audits


def test_claude_cannot_dismiss_a_loan_repayment_to_raise_safe_to_spend(world):
    bill = world.linked_bill()
    safe = world.summary()["safe_to_spend"]
    res = world.dismiss(bill, dry_run=False)
    assert res.status_code == 409
    assert world.rule(bill).status == "confirmed"
    assert world.summary()["safe_to_spend"] == safe


def test_claude_may_rename_a_linked_bill(world):
    bill = world.linked_bill()
    assert world.update(bill, dry_run=False, label="Car loan").status_code == 200


def test_undoing_an_earlier_claude_change_cannot_rewrite_a_linked_bill(world):
    bill = world.commitment(label="LOAN DD", amount="150.00")
    applied = world.update(bill, dry_run=False, amount="200.00")
    assert applied.status_code == 200, applied.text
    assert world.loan()["linked_commitment"]["id"] == str(bill)  # same amount and cadence: taken over
    audit_id = world.db.query(AuditEntry.id).filter(AuditEntry.target_id == bill).scalar()
    res = world.client.post(f"{API}/audit/{audit_id}/undo", headers=_bearer(world.web))
    assert res.status_code == 409
    assert world.rule(bill).amount == Decimal("200.00")


# --------------------------------------------------------------------------- #
# Detection and Claude's view
# --------------------------------------------------------------------------- #
def test_detection_never_suggests_a_linked_repayment_again(world):
    world.linked_bill()
    with world.as_user():
        account = _account(world.db, world.user.id, name="Current")
        for n, months_back in enumerate((3, 2, 1)):
            when = _add_months(NEXT, -months_back)  # the loan's own payment day
            world.db.add(Transaction(
                account_id=account.id, external_id=f"tx-loan-{n}", transaction_type="debit",
                amount=Decimal("200.00"), description="EXAMPLE BANK LOAN",
                transaction_date=datetime(when.year, when.month, when.day, tzinfo=timezone.utc),
            ))
            world.db.add(Transaction(
                account_id=account.id, external_id=f"tx-gym-{n}", transaction_type="debit",
                amount=Decimal("30.00"), description="GYM LTD",
                transaction_date=datetime(when.year, when.month, when.day, tzinfo=timezone.utc),
            ))
        world.db.commit()
    rules = world.client.get(f"{API}/analytics/commitments", headers=_bearer(world.web)).json()
    suggested = [r["label"] for r in rules if r["status"] == "suggested"]
    assert suggested == ["GYM LTD"]  # the gym is still suggested; the loan isn't


def test_claudes_summary_carries_liabilities_as_one_total_only(world):
    world.loan()
    summary = world.summary(token=world.mcp)
    assert {k for k in summary if "liabilit" in k or "loan" in k} == {"liabilities_total"}
    assert Decimal(summary["liabilities_total"]) == Decimal("9000.00")
    assert "Example Bank" not in str({k: v for k, v in summary.items() if k != "accounts"})


def test_a_linked_commitment_is_listed_as_linked(world):
    bill = world.linked_bill()
    rules = world.client.get(f"{API}/analytics/commitments", headers=_bearer(world.web)).json()
    (row,) = [r for r in rules if r["id"] == str(bill)]
    assert row["linked_liability"] is True
    assert all(r["linked_liability"] is False for r in rules if r["id"] != str(bill))


def test_nothing_is_counted_twice_after_the_guards(world):
    world.linked_bill()
    commitments = world.db.query(CommitmentRule).filter(CommitmentRule.user_id == world.user.id).count()
    assert commitments == 1


def test_a_loan_from_american_express_still_counts_beside_the_amex_card(world):
    # sec on #183: the bill a liability creates is labelled with the lender,
    # and "American Express ..." is an Amex repayment descriptor. It must
    # never be tied to the card, or the card's (larger) repayment would
    # replace it in safe-to-spend and the forecast.
    world.amex_card(owed="1500.00")
    with world.as_user():
        _account(world.db, world.user.id, name="Current", balance="5000")  # so safe-to-spend isn't floored at £0
    before = world.summary()
    bill = uuid.UUID(world.loan(lender="American Express")["linked_commitment"]["id"])
    after = world.summary()

    assert world.rule(bill).card_account_id is None
    assert Decimal(after["committed_before_payday"]) - Decimal(before["committed_before_payday"]) == Decimal("200.00")
    assert Decimal(before["safe_to_spend"]) - Decimal(after["safe_to_spend"]) == Decimal("200.00")
    f = world.client.get(f"{API}/analytics/forecast?horizon=90", headers=_bearer(world.web)).json()
    labels = [e["label"] for p in f["timeline"] for e in p["events"]]
    assert labels.count("American Express") == 3 and "Amex Gold" in labels


def test_a_linked_bill_tied_to_a_card_before_this_change_is_still_counted(world):
    # Backstop: a stored tie (from before the guard) is ignored for a linked bill.
    card_id = world.amex_card(owed="1500.00")
    bill = world.linked_bill()
    before = Decimal(world.summary()["committed_before_payday"])
    with world.as_user():
        rule = world.db.get(CommitmentRule, bill)
        rule.card_account_id, rule.card_link_source = card_id, "user"
        world.db.commit()
    assert Decimal(world.summary()["committed_before_payday"]) == before


def test_an_unrelated_bill_of_the_same_amount_is_still_suggested(world):
    # sec on #183 (medium): only payments on the repayment's own day are the loan.
    world.linked_bill()  # £200 a month, next payment on NEXT
    with world.as_user():
        account = _account(world.db, world.user.id, name="Current")
        for n, months_back in enumerate((3, 2, 1)):
            when = _add_months(TODAY, -months_back) - timedelta(days=12)  # a different day of the month
            world.db.add(Transaction(
                account_id=account.id, external_id=f"tx-nursery-{n}", transaction_type="debit",
                amount=Decimal("200.00"), description="NURSERY FEES",
                transaction_date=datetime(when.year, when.month, when.day, tzinfo=timezone.utc),
            ))
        world.db.commit()
    rules = world.client.get(f"{API}/analytics/commitments", headers=_bearer(world.web)).json()
    assert [r["label"] for r in rules if r["status"] == "suggested"] == ["NURSERY FEES"]
