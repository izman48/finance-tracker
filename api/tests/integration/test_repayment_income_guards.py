"""A payment marked as paid back is never income (T-03-3 P4; PRD decision 3,
AC-28, AC-5 income, AC-14 data; T-03-2 section 4).

A credit can become income in three ways: recurring-income detection, settling
a planned income item, and clearing a late income. A marked credit takes part
in none of them; an unmarked one behaves as before. Marking is blocked for a
credit that currently settles a planned income or clears a confirmed income
(`income_locked_credit_ids`), and warned for a payer who has an income
commitment (`income_commitment_payers`).
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import user_crypto
from app.models import CommitmentRule, PlannedItem, RepaymentMark, User
from app.services import repayment_guards
from app.services.analytics.commitments import detect_recurring
from app.services.analytics.late_income import late_incomes
from app.services.analytics.planned_matching import planned_states
from tests.clock import TODAY
from tests.integration.test_transactions_endpoint import _account, _tx

# Late income and planned matching take "today" as an argument; a fixed
# mid-month day keeps cadence steps off the 29th to 31st.
DAY = date(2026, 11, 15)


class Ledger:
    def __init__(self, db):
        self.db = db
        self.user = User(email="guards@example.com", hashed_password="x")
        db.add(self.user)
        db.commit()
        self.dek = user_crypto.current_dek.get()
        self.account = _account(db, self.user.id)

    def credit(self, amount, on, payer="SAM SMITH DINNER"):
        tx = _tx(self.db, self.account, amount, on, ttype="credit", merchant=payer)
        return tx.id

    def mark(self, credit_id, active=True):
        self.db.add(RepaymentMark(user_id=self.user.id, credit_transaction_id=credit_id, category="Eating out",
                                  amount=Decimal("1.00"), label="Sam", active=active, created_via="mcp"))
        self.db.commit()

    def income(self, label, amount, next_date, status="confirmed"):
        rule = CommitmentRule(
            user_id=self.user.id, direction="income", label=label, amount=Decimal(amount), cadence="monthly",
            next_date=next_date, source="manual", status=status,
        )
        self.db.add(rule)
        self.db.commit()
        self.db.execute(text("UPDATE commitment_rules SET created_at = :t WHERE id = :id"),
                        {"t": datetime(2026, 1, 1, tzinfo=timezone.utc), "id": rule.id.hex})
        self.db.commit()
        return rule.id

    def planned_income(self, name, amount, on):
        item = PlannedItem(user_id=self.user.id, name=name, direction="income", kind="one_off",
                           start_date=on, amount=Decimal(amount))
        self.db.add(item)
        self.db.commit()
        return item


@pytest.fixture
def ledger(db_session):
    return Ledger(db_session)


# --- marked credits never become income (AC-28) --------------------------------------


@pytest.mark.parametrize("marked", [False, True])
def test_detection_skips_marked_credits(ledger, db_session, marked):
    ids = [ledger.credit("20.00", TODAY - timedelta(days=d)) for d in (70, 40, 10)]
    if marked:
        for credit_id in ids:
            ledger.mark(credit_id)

    incomes = [c for c in detect_recurring(db_session, ledger.user) if c["direction"] == "income"]

    assert len(incomes) == (0 if marked else 1)


@pytest.mark.parametrize("marked", [False, True])
def test_a_marked_credit_never_settles_a_planned_income(ledger, db_session, marked):
    item = ledger.planned_income("Deposit refund", "60.00", DAY - timedelta(days=3))
    credit_id = ledger.credit("60.00", DAY - timedelta(days=2), payer="DEPOSIT REFUND LTD")
    if marked:
        ledger.mark(credit_id)

    state = planned_states(db_session, ledger.user, [item], DAY)[item.id]

    assert state.matched_transaction_id == (None if marked else credit_id)


@pytest.mark.parametrize("marked", [False, True])
def test_a_marked_credit_never_clears_a_late_income(ledger, db_session, marked):
    rule_id = ledger.income("Acme Payroll", "1000.00", DAY - timedelta(days=10))
    credit_id = ledger.credit("1000.00", DAY - timedelta(days=10), payer="Acme Payroll")
    if marked:
        ledger.mark(credit_id)

    assert (rule_id in late_incomes(db_session, ledger.user, DAY)) is marked


def test_an_unmarked_mark_no_longer_hides_the_credit(ledger, db_session):
    credit_id = ledger.credit("1000.00", DAY - timedelta(days=10), payer="Acme Payroll")
    ledger.income("Acme Payroll", "1000.00", DAY - timedelta(days=10))
    ledger.mark(credit_id, active=False)

    assert late_incomes(db_session, ledger.user, DAY) == {}


# --- what blocks or warns a new mark (AC-14 data) --------------------------------------


def test_a_credit_settling_a_planned_income_is_locked(ledger, db_session):
    ledger.planned_income("Deposit refund", "60.00", DAY - timedelta(days=3))
    refund = ledger.credit("60.00", DAY - timedelta(days=2), payer="DEPOSIT REFUND LTD")
    sam = ledger.credit("50.00", DAY - timedelta(days=2))  # an exact £60 could settle it too

    locked = repayment_guards.income_locked_credit_ids(db_session, ledger.user, DAY)

    assert locked == {refund: "planned_income"}
    assert sam not in locked


def test_a_credit_paying_a_confirmed_income_is_locked_even_inside_the_grace_days(ledger, db_session):
    ledger.income("Acme Payroll", "1000.00", DAY - timedelta(days=1))  # not late yet, but paid by this
    pay = ledger.credit("1000.00", DAY - timedelta(days=1), payer="Acme Payroll")

    assert repayment_guards.income_locked_credit_ids(db_session, ledger.user, DAY) == {pay: "late_income"}


def test_a_credit_paying_a_suggested_income_is_not_locked(ledger, db_session):
    ledger.income("Acme Payroll", "1000.00", DAY - timedelta(days=10), status="suggested")
    ledger.credit("1000.00", DAY - timedelta(days=10), payer="Acme Payroll")

    assert repayment_guards.income_locked_credit_ids(db_session, ledger.user, DAY) == {}


def test_a_payer_with_an_income_commitment_is_warned(ledger, db_session):
    ledger.income("Sam Smith", "50.00", DAY + timedelta(days=5), status="suggested")
    ledger.income("Old Job", "900.00", DAY + timedelta(days=5), status="dismissed")
    sam = ledger.credit("60.00", DAY - timedelta(days=2), payer="FASTER PAYMENT SAM SMITH DINNER")
    jo = ledger.credit("50.00", DAY - timedelta(days=2), payer="JO BLOGGS PIZZA")
    old = ledger.credit("50.00", DAY - timedelta(days=2), payer="OLD JOB")

    warned = repayment_guards.income_commitment_payers(db_session, ledger.user, [sam, jo, old])

    assert warned == {sam}


def test_guards_read_only_the_users_own_credits(ledger, db_session):
    other = User(email="other@example.com", hashed_password="x")
    db_session.add(other)
    db_session.commit()
    ledger.income("Sam Smith", "50.00", DAY + timedelta(days=5))
    theirs = _tx(db_session, _account(db_session, other.id, name="Theirs"), "60.00", DAY, ttype="credit",
                 merchant="SAM SMITH").id

    assert repayment_guards.income_commitment_payers(db_session, ledger.user, [theirs]) == set()


def test_undo_of_an_unmark_is_refused_once_the_credit_is_income(client, db_session):
    """Undo re-checks the income block as well as the caps (eng-b on #272): a
    credit that settles a planned income now must not be marked again."""
    from tests.integration.test_repayment_marks import Claude

    c = Claude(client, db_session)
    sam = c.ledger.credit("60.00", when=TODAY - timedelta(days=2))
    mark_id = uuid.UUID(c.add_mark(sam, "60.00", category="Eating out")["target_id"])
    removed = c.unmark(mark_id)
    c.ledger.as_user(lambda: db_session.add(PlannedItem(
        user_id=c.user.id, name="Sam", direction="income", kind="one_off", start_date=TODAY - timedelta(days=3),
        amount=Decimal("60.00"))) or db_session.commit())

    res = c.undo(removed["audit_id"])

    assert res.status_code == 409 and "changed since" in res.json()["detail"]
    assert c.get(RepaymentMark, mark_id).active is False
