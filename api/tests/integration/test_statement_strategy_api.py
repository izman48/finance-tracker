"""The statements response under the `statement_balance` strategy (T-10-3):
the missing-statement prompt and `next_payment` (ux A4), which must agree
with the forecast because it comes from the same function.

Synthetic fixture: statement £5,000, current balance £6,000.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import AccountSetting
from tests.clock import TODAY
from tests.integration.test_card_statements_api import API, STATEMENT, Person


@pytest.fixture
def alice(client, db_session):
    person = Person(client, db_session, "alice@example.com")
    with person.key():
        db_session.add(AccountSetting(
            user_id=person.user_id, account_id=person.card_id, role="credit",
            repayment_strategy="statement_balance", repayment_cadence="card_due_date",
            pay_from_account_id=person.current_id,
        ))
        db_session.commit()
    return person


def _passed_statement(days_ago=2):
    due = TODAY - timedelta(days=days_ago)
    return {"statement_balance": "5000.00", "statement_date": (due - timedelta(days=25)).isoformat(),
            "due_date": due.isoformat()}


def test_missing_statement_after_due_date_prompts_user(alice):
    alice.add(_passed_statement())

    assert alice.get().json()["missing_statement"] is True


def test_no_prompt_while_the_due_date_is_ahead_or_a_newer_statement_exists(alice):
    assert alice.get().json()["missing_statement"] is False  # no statement: the empty state asks instead
    alice.add(_passed_statement(days_ago=33))
    alice.add()  # the newer one, due in 10 days

    assert alice.get().json()["missing_statement"] is False


def test_next_payment_is_the_statement_on_its_due_date_from_the_pay_from_account(alice):
    alice.add()

    nxt = alice.get().json()["next_payment"]

    assert nxt == {"amount": "5000.00", "date": STATEMENT["due_date"], "from_account_name": "alice@example.com current"}


def test_next_payment_agrees_with_the_summary_and_the_forecast(alice):
    alice.add()

    nxt = alice.get().json()["next_payment"]
    summary = alice.client.get(f"{API}/analytics/summary", headers=alice.headers).json()
    forecast = alice.client.get(f"{API}/analytics/forecast?horizon=60", headers=alice.headers).json()
    first_in_summary = next(r for r in summary["next_repayments"] if r["account_id"] == str(alice.card_id))
    first_in_forecast = next(
        (p["date"], e["amount"]) for p in forecast["timeline"] for e in p["events"] if e["kind"] == "repayment"
    )

    assert (nxt["date"], Decimal(nxt["amount"])) == (first_in_summary["due_date"], Decimal(first_in_summary["amount"]))
    assert (nxt["date"], -Decimal(nxt["amount"])) == (first_in_forecast[0], Decimal(first_in_forecast[1]))


def test_with_no_statement_next_payment_is_the_full_balance(alice):
    nxt = alice.get().json()["next_payment"]

    assert Decimal(nxt["amount"]) == Decimal("6000")
    assert nxt["date"] == (TODAY + timedelta(days=30)).isoformat()


def test_a_card_with_no_repayment_plan_has_no_next_payment(alice, db_session):
    assert alice.get(alice.other_card_id).json()["next_payment"] is None
