"""Repayment marks: the table (T-03-3 P1; PRD T-03-1 "Model", T-03-2 T10).

A mark says "this much of an incoming payment paid back a spend, or a
category". Its amount and label are encrypted; ids, category, `active` and
`created_via` are plain. Nothing user-visible reads marks yet.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core import user_crypto
from app.models import RepaymentMark, Transaction, User
from app.services.key_loss_purge import purge_data_under_lost_key
from tests.integration.test_transactions_endpoint import _account, _tx

DINNER_DAY = date(2026, 10, 2)
T0 = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


class Ledger:
    """A user's account with helpers for transactions and marks, written
    under that user's key."""

    def __init__(self, db, user_id, dek):
        self.db, self.user_id, self.dek = db, user_id, dek
        self.n = 0
        self.account = self.as_user(lambda: _account(db, user_id))

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def spend(self, amount, category="Eating out") -> Transaction:
        return self.as_user(lambda: _tx(self.db, self.account, amount, DINNER_DAY, category=category))

    def credit(self, amount, when=DINNER_DAY + timedelta(days=2)) -> Transaction:
        return self.as_user(lambda: _tx(self.db, self.account, amount, when, ttype="credit", merchant="SAM"))

    def mark(self, credit, amount, spend=None, category=None, active=True, label="Sam, dinner") -> RepaymentMark:
        self.n += 1

        def make():
            row = RepaymentMark(
                user_id=self.user_id, credit_transaction_id=credit.id,
                spend_transaction_id=spend.id if spend else None, category=category,
                amount=Decimal(amount), label=label, active=active, created_via="mcp",
                created_at=T0 + timedelta(minutes=self.n),
            )
            self.db.add(row)
            self.db.commit()
            return row
        return self.as_user(make)


@pytest.fixture
def ledger(db_session):
    user = User(email="marks@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    return Ledger(db_session, user.id, user_crypto.current_dek.get())


@pytest.fixture
def fk_on(db_session):
    """Foreign keys enforced, as on Postgres (the cascades rely on them)."""
    db_session.commit()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    yield
    db_session.rollback()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")


# --- the table -------------------------------------------------------------------


def test_amount_and_label_are_encrypted_and_the_rest_is_plain(ledger, db_session):
    dinner, sam = ledger.spend("200.00"), ledger.credit("60.00")
    ledger.mark(sam, "60.00", spend=dinner, label="Sam £60, Pizza Express")

    raw = db_session.execute(text("SELECT amount, label, active, created_via FROM repayment_marks")).one()
    assert "60" not in raw.amount and "Pizza" not in raw.label
    assert bool(raw.active) is True and raw.created_via == "mcp"


@pytest.mark.parametrize("target", ["neither", "both"])
def test_a_mark_needs_exactly_one_of_spend_or_category(ledger, db_session, target):
    dinner, sam = ledger.spend("200.00"), ledger.credit("60.00")
    with pytest.raises(IntegrityError):
        if target == "neither":
            ledger.mark(sam, "60.00")
        else:
            ledger.mark(sam, "60.00", spend=dinner, category="Eating out")


def test_one_active_mark_per_credit_and_spend(ledger, db_session):
    dinner, sam = ledger.spend("200.00"), ledger.credit("60.00")
    ledger.mark(sam, "30.00", spend=dinner, active=False)  # an unmarked one doesn't count
    ledger.mark(sam, "30.00", spend=dinner)
    with pytest.raises(IntegrityError):
        ledger.mark(sam, "30.00", spend=dinner)


def test_one_active_mark_per_credit_and_category(ledger, db_session):
    sam = ledger.credit("60.00")
    ledger.mark(sam, "30.00", category="Eating out")
    ledger.mark(sam, "30.00", category="Groceries")  # another category is fine
    with pytest.raises(IntegrityError):
        ledger.mark(sam, "10.00", category="Eating out")


@pytest.mark.parametrize("deleted", ["credit", "spend"])
def test_deleting_either_transaction_deletes_its_marks(ledger, db_session, fk_on, deleted):
    dinner, sam = ledger.spend("200.00"), ledger.credit("60.00")
    ledger.mark(sam, "60.00", spend=dinner)
    gone = sam if deleted == "credit" else dinner
    db_session.execute(text("DELETE FROM transactions WHERE id = :id"), {"id": gone.id.hex})
    db_session.commit()
    assert db_session.execute(text("SELECT count(*) FROM repayment_marks")).scalar() == 0


def test_deleting_the_user_deletes_their_marks(ledger, db_session, fk_on):
    ledger.mark(ledger.credit("60.00"), "60.00", category="Eating out")
    db_session.execute(text("DELETE FROM users"))
    db_session.commit()
    assert db_session.execute(text("SELECT count(*) FROM repayment_marks")).scalar() == 0


def test_the_key_loss_purge_deletes_marks_before_their_transactions(ledger, db_session, fk_on):
    ledger.mark(ledger.credit("60.00"), "60.00", spend=ledger.spend("200.00"))
    purge_data_under_lost_key(db_session, ledger.user_id)
    db_session.commit()
    assert db_session.execute(text("SELECT count(*) FROM repayment_marks")).scalar() == 0
    assert db_session.execute(text("SELECT count(*) FROM transactions")).scalar() == 0
