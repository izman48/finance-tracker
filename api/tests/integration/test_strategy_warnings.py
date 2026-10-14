"""Repayment strategy warnings and the card APR (T-10-5, ux A1/A2, sec A2).

Warnings come back on the settings save and on the statements load (the
card settings view), as a code plus values; the UI words them. Synthetic
fixture: statement £5,000, current balance £6,000, pay-from account £1,000.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models import Account
from tests.clock import TODAY
from tests.integration.test_card_statements_api import API, Person

DUE = TODAY + timedelta(days=10)


@pytest.fixture
def alice(client, db_session):
    return Person(client, db_session, "alice@example.com")


def _settings(person, account_id=None, **body):
    return person.client.patch(f"{API}/analytics/accounts/{account_id or person.card_id}/settings",
                               json=body, headers=person.headers)


def _plan(person, **body):
    base = {"role": "credit", "pay_from_account_id": str(person.current_id)}
    res = _settings(person, **{**base, **body})
    assert res.status_code == 200, res.text
    return res.json()["warnings"]


def _codes(warnings):
    return [w["code"] for w in warnings]


def _one(warnings, code):
    (w,) = [w for w in warnings if w["code"] == code]
    return w["values"]


def _roomy(person):
    """Plenty in the pay-from account, so no overdraft warning muddies a test."""
    with person.key():
        acc = person.db.query(Account).filter(Account.id == person.current_id).one()
        acc.current_balance = Decimal("20000")
        person.db.commit()


# --- interest ---------------------------------------------------------------------


def test_minimum_strategy_flags_interest_cost(alice):
    alice.add()
    _roomy(alice)

    warnings = _plan(alice, repayment_strategy="fixed", repayment_fixed_amount="300", repayment_cadence="card_due_date",
                     card_apr="20.00")

    # Hand-checked: (5,000 - 300) x ((1.20)^(1/12) - 1) = 4,700 x 0.0153095 = 71.95.
    assert _one(warnings, "interest_cost") == {"monthly_interest": "71.95", "apr": "20.00"}


def test_without_an_apr_the_interest_warning_has_no_figure(alice):
    alice.add()
    _roomy(alice)

    warnings = _plan(alice, repayment_strategy="fixed", repayment_fixed_amount="300", repayment_cadence="card_due_date")

    assert _one(warnings, "interest_cost") == {"monthly_interest": None, "apr": None}


@pytest.mark.parametrize("strategy", ["statement_balance", "full_balance"])
def test_paying_the_statement_or_more_has_no_interest_warning(alice, strategy):
    alice.add()
    _roomy(alice)

    assert "interest_cost" not in _codes(_plan(alice, repayment_strategy=strategy, repayment_cadence="card_due_date",
                                               card_apr="20.00"))


def test_no_statement_no_interest_warning(alice):
    _roomy(alice)
    warnings = _plan(alice, repayment_strategy="fixed", repayment_fixed_amount="300", repayment_cadence="card_due_date")
    assert "interest_cost" not in _codes(warnings)


# --- late fee -----------------------------------------------------------------------


def test_pay_day_after_due_date_flags_late_fee_risk(alice):
    alice.add({"statement_balance": "5000.00", "statement_date": (TODAY - timedelta(days=14)).isoformat(),
               "due_date": DUE.isoformat()})
    _roomy(alice)
    late = DUE + timedelta(days=5)

    warnings = _plan(alice, repayment_strategy="statement_balance", repayment_cadence="monthly", repayment_day=late.day)

    assert _one(warnings, "late_fee_risk") == {
        "pay_date": late.isoformat(), "due_date": DUE.isoformat(), "repayment_day": str(late.day),
    }


@pytest.mark.parametrize("cadence, day_offset", [("monthly", -2), ("card_due_date", None)])
def test_paying_by_the_due_date_has_no_late_fee_warning(alice, cadence, day_offset):
    alice.add()
    _roomy(alice)
    body = {"repayment_strategy": "statement_balance", "repayment_cadence": cadence}
    if day_offset is not None:
        body["repayment_day"] = (DUE + timedelta(days=day_offset)).day

    assert "late_fee_risk" not in _codes(_plan(alice, **body))


# --- overdraft ----------------------------------------------------------------------


def test_payment_breaching_source_overdraft_is_flagged(alice):
    alice.add()
    _settings(alice, alice.current_id, role="spending", overdraft_limit="500")

    warnings = _plan(alice, repayment_strategy="statement_balance", repayment_cadence="card_due_date")

    # Pay-from £1,000 - £5,000 on the due date = -£4,000, past its £500 limit.
    assert _one(warnings, "overdraft_breach") == {
        "amount": "5000.00", "account_name": "alice@example.com current", "balance": "-4000.00",
        "limit": "500.00", "date": DUE.isoformat(),
    }


def test_with_no_overdraft_the_warning_is_below_zero(alice):
    alice.add()

    values = _one(_plan(alice, repayment_strategy="statement_balance", repayment_cadence="card_due_date"),
                  "overdraft_breach")

    assert values["limit"] is None and values["balance"] == "-4000.00"


def test_enough_in_the_source_account_has_no_overdraft_warning(alice):
    alice.add()
    _roomy(alice)

    assert "overdraft_breach" not in _codes(_plan(alice, repayment_strategy="statement_balance",
                                                  repayment_cadence="card_due_date"))


# --- where warnings appear --------------------------------------------------------------


def test_the_card_settings_load_carries_the_warnings_and_the_apr(alice):
    alice.add()
    _plan(alice, repayment_strategy="fixed", repayment_fixed_amount="300", repayment_cadence="card_due_date",
          card_apr="20.00")

    body = alice.get().json()

    assert "interest_cost" in _codes(body["warnings"])
    assert body["card_apr"] == "20.00"


def test_a_non_credit_account_has_no_warnings(alice):
    res = _settings(alice, alice.current_id, role="spending", overdraft_limit="500")
    assert res.status_code == 200 and res.json()["warnings"] == []


# --- the card APR (sec A2) -----------------------------------------------------------------


@pytest.mark.parametrize("apr", ["-0.01", "100.01", "abc", 20.5, "20.001"])
def test_card_apr_is_validated(alice, apr):
    assert _settings(alice, role="credit", card_apr=apr).status_code == 422


def test_card_apr_limits_are_accepted_and_it_can_be_cleared(alice):
    for apr in ("0", "100.00", None):
        assert _settings(alice, role="credit", card_apr=apr).status_code == 200


def test_card_apr_is_only_for_credit_accounts(alice):
    assert _settings(alice, alice.current_id, role="spending", card_apr="20.00").status_code == 422


def test_card_apr_is_encrypted_at_rest(alice, db_session):
    _settings(alice, role="credit", card_apr="19.90")
    raw = db_session.execute(text("SELECT card_apr FROM account_settings WHERE card_apr IS NOT NULL")).scalar()
    assert raw and "19.9" not in raw


def test_no_warnings_while_a_linked_card_bill_is_counted_instead(alice, db_session):
    """eng-b on #188: while a commitment is tied to the card, the forecast
    may pay that bill instead of the repayment (same rule as next_payment),
    so warnings about the repayment would describe a payment that isn't
    planned. Repro: fixed £300 at 24% APR with a linked £5,500 card bill."""
    from app.models import CommitmentRule

    alice.add()
    with alice.key():
        db_session.add(CommitmentRule(
            user_id=alice.user_id, direction="expense", label="Card bill", amount=Decimal("5500"),
            cadence="monthly", next_date=DUE, source="manual", status="confirmed",
            card_account_id=alice.card_id, card_link_source="user",
        ))
        db_session.commit()

    warnings = _plan(alice, repayment_strategy="fixed", repayment_fixed_amount="300", repayment_cadence="card_due_date",
                     card_apr="24.00")

    assert warnings == []
    assert alice.get().json()["warnings"] == []
