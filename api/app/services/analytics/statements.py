"""Card statements: which one is current, what is still due, what is unbilled.

Rules (liabilities and repayments spec, "Statement balance"):
- The current statement is the one with the latest statement date; for the
  same date a manual row wins over a provider row.
- Payments to the card after the statement date reduce the amount still due;
  at £0 the statement is paid.
- Unbilled spend = what is owed now − the amount still due, never below £0,
  and it never reduces the amount still due.

Fail-safe: only credits we can identify as payments count. A refund or any
other unidentified credit leaves the full statement due (overstates, never
hides).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.models import StatementSource

from .common import _d

ZERO = Decimal("0")
# Card-side payment descriptors ("PAYMENT RECEIVED - THANK YOU"). Whole word,
# so a merchant like "PAYMENTSENSE" refunding a purchase is not a payment.
_PAYMENT_WORD = re.compile(r"\bpayment\b")


@dataclass(frozen=True)
class StatementPosition:
    statement: object
    payments_since_statement: Decimal
    amount_still_due: Decimal
    unbilled: Decimal

    @property
    def paid(self) -> bool:
        return self.amount_still_due == ZERO


def current_statement(statements):
    """The latest statement; manual beats provider on the same date."""
    if not statements:
        return None
    return max(statements, key=lambda s: (s.statement_date, s.source == StatementSource.MANUAL.value))


def is_payment_to_card(tx) -> bool:
    """A credit on the card account that we can identify as a payment."""
    if tx.transaction_type != "credit":
        return False
    if tx.counts_as_override is not None:
        return tx.counts_as_override == "card_payment"
    text = f"{tx.description or ''} {tx.merchant_name or ''}".lower()
    return bool(_PAYMENT_WORD.search(text))


def payments_since(statement_date: date, card_transactions) -> Decimal:
    """Identified payments dated after the statement closed (a payment on the
    closing day is already in the statement)."""
    first_day = statement_date + timedelta(days=1)
    return sum(
        (_d(tx.amount) for tx in card_transactions
         if tx.transaction_date.date() >= first_day and is_payment_to_card(tx)),
        ZERO,
    )


def statement_position(statement, owed: Decimal, card_transactions) -> StatementPosition:
    """Amount still due and unbilled spend for a statement, given what is
    owed on the card now (from `balance_sign.credit_owed`)."""
    paid = payments_since(statement.statement_date, card_transactions)
    still_due = max(ZERO, _d(statement.statement_balance) - paid)
    unbilled = max(ZERO, _d(owed) - still_due)
    return StatementPosition(
        statement=statement,
        payments_since_statement=paid,
        amount_still_due=still_due,
        unbilled=unbilled,
    )


MAX_DAYS_TO_DUE = 60


def check_statement(statement_balance, statement_date: date, due_date: date, minimum_due, today: date) -> None:
    """Rules that need today or the whole statement (S-5). Raises ValueError
    with a message the user can act on."""
    if statement_date > today:
        raise ValueError("The statement date can't be in the future.")
    if not statement_date <= due_date <= statement_date + timedelta(days=MAX_DAYS_TO_DUE):
        raise ValueError("The due date must be on or after the statement date, and no more than 60 days after it.")
    if minimum_due is not None and _d(minimum_due) > _d(statement_balance):
        raise ValueError("The minimum payment can't be more than the statement balance.")
