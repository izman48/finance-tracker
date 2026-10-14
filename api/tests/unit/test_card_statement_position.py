"""Amount still due and unbilled spend for a card statement (T-10-1).

Synthetic fixture (the repo is public): statement £5,000, current balance
£6,000, so £1,000 was spent after the statement closed.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.analytics.statements import current_statement, statement_position

STATEMENT_DATE = date(2026, 10, 3)
DUE_DATE = date(2026, 10, 31)


def _statement(balance="5000.00", statement_date=STATEMENT_DATE, source="manual"):
    return SimpleNamespace(
        id="s-1", statement_balance=Decimal(balance), statement_date=statement_date,
        due_date=DUE_DATE, minimum_due=None, source=source,
    )


def _tx(amount, on: date, ttype="credit", description="PAYMENT RECEIVED - THANK YOU", override=None):
    return SimpleNamespace(
        transaction_type=ttype, amount=Decimal(amount), description=description, merchant_name=None,
        transaction_date=datetime(on.year, on.month, on.day, 12, tzinfo=timezone.utc),
        counts_as_override=override,
    )


AFTER = STATEMENT_DATE + timedelta(days=5)


def test_unbilled_spend_is_current_minus_outstanding_statement():
    position = statement_position(_statement(), owed=Decimal("6000"), card_transactions=[])

    assert position.amount_still_due == Decimal("5000.00")
    assert position.unbilled == Decimal("1000.00")
    assert position.payments_since_statement == Decimal("0")
    assert position.paid is False


def test_payment_after_statement_reduces_amount_due():
    paid_some = statement_position(_statement(), owed=Decimal("5000"), card_transactions=[_tx("1000", AFTER)])
    assert paid_some.amount_still_due == Decimal("4000.00")
    assert paid_some.unbilled == Decimal("1000.00")
    assert paid_some.paid is False

    paid_all = statement_position(_statement(), owed=Decimal("1000"), card_transactions=[_tx("5000", AFTER)])
    assert paid_all.amount_still_due == Decimal("0")
    assert paid_all.unbilled == Decimal("1000")
    assert paid_all.paid is True


def test_payments_on_or_before_the_statement_date_are_already_in_the_statement():
    txns = [_tx("1000", STATEMENT_DATE), _tx("500", STATEMENT_DATE - timedelta(days=2))]

    position = statement_position(_statement(), owed=Decimal("6000"), card_transactions=txns)

    assert position.amount_still_due == Decimal("5000.00")


def test_unidentified_credits_never_reduce_the_amount_due():
    """Fail-safe: a refund is not a payment we can identify, so the full
    statement stays due (overstates, never hides)."""
    refund = _tx("300", AFTER, description="ACME STORES REFUND")

    position = statement_position(_statement(), owed=Decimal("5700"), card_transactions=[refund])

    assert position.amount_still_due == Decimal("5000.00")
    assert position.unbilled == Decimal("700.00")


def test_purchases_on_the_card_are_not_payments():
    purchase = _tx("40", AFTER, ttype="debit", description="PAYMENT TO ACME")

    position = statement_position(_statement(), owed=Decimal("6040"), card_transactions=[purchase])

    assert position.amount_still_due == Decimal("5000.00")


def test_the_users_counts_as_choice_beats_the_description():
    marked = _tx("1000", AFTER, description="REF 7781", override="card_payment")
    not_a_payment = _tx("200", AFTER, override="spending")

    position = statement_position(_statement(), owed=Decimal("4800"), card_transactions=[marked, not_a_payment])

    assert position.payments_since_statement == Decimal("1000")
    assert position.amount_still_due == Decimal("4000.00")


def test_negative_unbilled_shows_zero_and_never_reduces_the_amount_due():
    """A refund or overpayment can take the balance below the statement."""
    position = statement_position(_statement(), owed=Decimal("4500"), card_transactions=[])

    assert position.unbilled == Decimal("0")
    assert position.amount_still_due == Decimal("5000.00")


def test_overpaying_the_statement_marks_it_paid_with_nothing_due():
    position = statement_position(_statement(), owed=Decimal("0"), card_transactions=[_tx("6000", AFTER)])

    assert position.amount_still_due == Decimal("0")
    assert position.paid is True
    assert position.unbilled == Decimal("0")


def test_current_statement_is_the_latest_and_manual_wins_on_the_same_date():
    older = _statement(statement_date=STATEMENT_DATE - timedelta(days=30))
    provider = _statement(balance="4900.00", source="provider")
    manual = _statement(balance="5000.00", source="manual")

    assert current_statement([older, provider, manual]) is manual
    assert current_statement([provider, older]) is provider
    assert current_statement([]) is None
