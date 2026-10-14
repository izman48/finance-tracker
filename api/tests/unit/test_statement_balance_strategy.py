"""`statement_balance` strategy and the "card due date" pay day (T-10-3).

Synthetic fixture (the repo is public): statement £5,000 due in 10 days,
current balance £6,000, so £1,000 unbilled goes on the next due date.
Every unknown or fallback branch pays the full current balance (fail-safe).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest

from app.models import Account, AccountSetting, CardStatement, CommitmentRule, Transaction, User
from app.services import analytics_service as svc
from app.services.analytics.common import _add_months
from app.services.analytics.projections import _projected_commitments
from app.services.analytics.repayments import _repayment_schedule
from tests.clock import TODAY

DUE = TODAY + timedelta(days=10)
NEXT_DUE = _add_months(DUE, 1)
STATEMENT_DATE = TODAY - timedelta(days=14)


def _user(db):
    u = User(email=f"sb-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(u)
    db.commit()
    return u


def _account(db, user, atype, balance, name):
    a = Account(
        user_id=user.id, bank_connection_id=user.id, external_id=f"ext-{uuid.uuid4()}",
        provider_name="Test Bank", account_type=atype, display_name=name, current_balance=Decimal(balance),
    )
    db.add(a)
    db.commit()
    return a


class World:
    def __init__(self, db, strategy="statement_balance", cadence="card_due_date", balance="6000", **setting):
        self.db = db
        self.user = _user(db)
        self.current = _account(db, self.user, "TRANSACTION", "8000", "Test Current")
        db.add(AccountSetting(user_id=self.user.id, account_id=self.current.id, role="spending"))
        self.card = _account(db, self.user, "CREDIT_CARD", balance, "Test Card")
        db.add(AccountSetting(
            user_id=self.user.id, account_id=self.card.id, role="credit", repayment_strategy=strategy,
            repayment_cadence=cadence, pay_from_account_id=self.current.id, **setting,
        ))
        db.commit()

    def statement(self, balance="5000", statement_date=STATEMENT_DATE, due=DUE):
        self.db.add(CardStatement(
            user_id=self.user.id, account_id=self.card.id, statement_date=statement_date, due_date=due,
            statement_balance=Decimal(balance), source="manual",
        ))
        self.db.commit()

    def payment(self, amount, days_ago=2):
        when = TODAY - timedelta(days=days_ago)
        self.db.add(Transaction(
            account_id=self.card.id, external_id=f"tx-{uuid.uuid4()}", transaction_type="credit",
            amount=Decimal(amount), description="PAYMENT RECEIVED - THANK YOU",
            transaction_date=datetime(when.year, when.month, when.day, 12, tzinfo=timezone.utc),
        ))
        self.db.commit()

    def repayments(self, days=80):
        events = svc.repayment_events(self.db, self.user, TODAY, TODAY + timedelta(days=days))
        return [(r["due_date"], r["amount"]) for r in events]

    def forecast_repayments(self, horizon="80"):
        f = svc.get_forecast(self.db, self.user, horizon=horizon)
        return [(p["date"], e["amount"]) for p in f["timeline"] for e in p["events"] if e["kind"] == "repayment"]


def _d(day) -> str:
    return day.isoformat()


# --- the strategy --------------------------------------------------------------


def test_statement_balance_strategy_pays_statement_on_due_date(db_session):
    w = World(db_session)
    w.statement()

    assert w.repayments() == [(DUE, Decimal("5000")), (NEXT_DUE, Decimal("1000"))]
    # The forecast takes both from the pay-from account.
    assert [(str(d), a) for d, a in w.forecast_repayments()] == [
        (_d(DUE), Decimal("-5000")), (_d(NEXT_DUE), Decimal("-1000")),
    ]


def test_statement_balance_strategy_pays_last_statement_on_due_date(db_session):
    w = World(db_session)
    w.statement(balance="4200", statement_date=STATEMENT_DATE - timedelta(days=31), due=DUE - timedelta(days=31))
    w.statement()

    assert w.repayments() == [(DUE, Decimal("5000")), (NEXT_DUE, Decimal("1000"))]


def test_statement_balance_carries_unbilled_to_next_due_date(db_session):
    """Paid in full: nothing on the statement's due date, the spend since it
    on the next one."""
    w = World(db_session, balance="1000")
    w.statement()
    w.payment("5000")

    assert w.repayments() == [(NEXT_DUE, Decimal("1000"))]


def test_a_part_paid_statement_pays_what_is_left(db_session):
    w = World(db_session, balance="5000")
    w.statement()
    w.payment("1000")

    assert w.repayments() == [(DUE, Decimal("4000")), (NEXT_DUE, Decimal("1000"))]


@pytest.mark.parametrize("balance", ["6000", "5700", "4500", "5000"])
def test_total_out_never_falls_below_full_balance(db_session, balance):
    full = World(db_session, strategy="full_balance", balance=balance)
    full.statement()
    by_statement = World(db_session, balance=balance)
    by_statement.statement()

    full_total = sum(a for _, a in full.repayments())
    statement_total = sum(a for _, a in by_statement.repayments())

    assert full_total == Decimal(balance)
    assert statement_total >= full_total


def test_statement_balance_on_day_x_pays_statement_then_unbilled(db_session):
    w = World(db_session, cadence="monthly", repayment_day=(TODAY + timedelta(days=5)).day)
    w.statement()
    first = svc.next_repayment_date(db_session.get(AccountSetting, _setting_id(w)), TODAY)

    assert w.repayments() == [(first, Decimal("5000")), (_add_months(first, 1), Decimal("1000"))]


def _setting_id(w):
    return w.db.query(AccountSetting.id).filter(AccountSetting.account_id == w.card.id).scalar()


def test_full_balance_on_day_x_includes_unbilled_spend(db_session):
    day = (TODAY + timedelta(days=5)).day
    w = World(db_session, strategy="full_balance", cadence="monthly", repayment_day=day)
    w.statement()

    events = w.repayments(days=40)

    assert len(events) == 1 and events[0][1] == Decimal("6000")
    assert events[0][0].day == day


def test_full_balance_on_the_card_due_date_pays_everything_on_the_statement_due_date(db_session):
    w = World(db_session, strategy="full_balance")
    w.statement()

    assert w.repayments() == [(DUE, Decimal("6000"))]


# --- fallbacks (fail-safe) ---------------------------------------------------------


def test_no_statement_pays_the_full_balance_30_days_from_today(db_session):
    w = World(db_session)

    assert w.repayments() == [(TODAY + timedelta(days=30), Decimal("6000"))]


def test_no_statement_uses_the_cards_configured_day_when_set(db_session):
    day = (TODAY + timedelta(days=5)).day
    w = World(db_session, repayment_day=day)

    events = w.repayments(days=40)

    assert len(events) == 1 and events[0] == (events[0][0], Decimal("6000"))
    assert events[0][0].day == day and TODAY <= events[0][0] <= TODAY + timedelta(days=31)


def test_statement_balance_with_no_pay_day_uses_the_card_due_date(db_session):
    w = World(db_session, cadence=None)
    w.statement()

    assert w.repayments() == [(DUE, Decimal("5000")), (NEXT_DUE, Decimal("1000"))]


def test_missing_statement_after_due_date_pays_full_balance_on_next_expected_due_date(db_session):
    """Until the user enters the new statement, the old one is not trusted:
    the full current balance goes on the next expected due date, never £0."""
    passed = TODAY - timedelta(days=2)
    w = World(db_session)
    w.statement(statement_date=passed - timedelta(days=25), due=passed)

    assert w.repayments() == [(_add_months(passed, 1), Decimal("6000"))]


def test_a_card_in_credit_pays_nothing(db_session):
    w = World(db_session, balance="0")
    w.statement()

    assert w.repayments() == []


@pytest.mark.parametrize("strategy", ["mystery", "STATEMENT", ""])
def test_unknown_strategy_falls_back_to_full_balance(db_session, strategy):
    w = World(db_session, strategy=strategy, cadence="monthly", repayment_day=(TODAY + timedelta(days=5)).day)
    w.statement()
    setting = db_session.get(AccountSetting, _setting_id(w))

    assert svc.repayment_amount(setting, Decimal("6000")) == Decimal("6000")
    assert _repayment_schedule(setting, Decimal("6000")) == [Decimal("6000")]
    assert [a for _, a in w.repayments(days=40)] == [Decimal("6000")]


# --- every surface goes through scheduled_outflows ----------------------------------


def test_summary_lists_the_statement_and_the_unbilled_as_next_repayments(db_session):
    w = World(db_session)
    w.statement()

    nxt = svc.get_summary(db_session, w.user)["next_repayments"]

    assert [(r["due_date"], r["amount"]) for r in nxt] == [(DUE, Decimal("5000")), (NEXT_DUE, Decimal("1000"))]


def test_summary_and_forecast_count_the_same_outflow(db_session):
    w = World(db_session)
    w.statement()

    committed = svc.get_summary(db_session, w.user)["committed_before_payday"]
    outflow = -sum((a for d, a in w.forecast_repayments(horizon="payday")), Decimal(0))

    assert committed == outflow == Decimal("5000")  # no payday: today + 30 holds the statement only


def test_linked_card_commitment_counts_once_and_the_larger_wins(db_session):
    w = World(db_session)
    w.statement()
    db_session.add(CommitmentRule(
        user_id=w.user.id, direction="expense", label="Card bill", amount=Decimal("300"), cadence="monthly",
        next_date=DUE, source="manual", status="confirmed", card_account_id=w.card.id, card_link_source="user",
    ))
    db_session.commit()

    committed = svc.get_summary(db_session, w.user)["committed_before_payday"]
    outflow = -sum((a for d, a in w.forecast_repayments(horizon="payday")), Decimal(0))
    projected = _projected_commitments(db_session, w.user, TODAY)

    assert committed == outflow == Decimal("5000")
    assert projected == []  # projections leave the card's repayment out too


@pytest.mark.parametrize("cadence", ["fortnightly", "Monthly", "card due date"])
def test_statement_balance_with_an_unknown_pay_day_uses_the_card_due_date(db_session, cadence):
    """Cadence is still free text until T-10-4a: an unknown value must never
    drop a payment or raise (eng-b, #175)."""
    with_statement = World(db_session, cadence=cadence)
    with_statement.statement()
    without = World(db_session, cadence=cadence)

    assert with_statement.repayments() == [(DUE, Decimal("5000")), (NEXT_DUE, Decimal("1000"))]
    assert without.repayments() == [(TODAY + timedelta(days=30), Decimal("6000"))]
    assert svc.get_summary(db_session, with_statement.user)["committed_before_payday"] == Decimal("5000")
