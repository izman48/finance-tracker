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
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CardStatement, StatementSource, Transaction
from app.services.balance_sign import credit_owed

from .common import _d

ZERO = Decimal("0")
# Card-side payment descriptors ("PAYMENT RECEIVED - THANK YOU"). Whole word,
# so a merchant like "PAYMENTSENSE" refunding a purchase is not a payment, and
# anything naming a refund or reversal is not one either: counting a refund as a payment
# would lower the amount due (the unsafe side). Card feeds' exact payment text
# is unverified; the user's counts_as choice beats this guess.
_PAYMENT_WORD = re.compile(r"\bpayment\b")
_REFUND_WORD = re.compile(r"\b(refund|reversal)")


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
    return bool(_PAYMENT_WORD.search(text)) and not _REFUND_WORD.search(text)


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


def position_for(db: Session, account, statement) -> StatementPosition:
    """The position of this card's statement, from the card's balance and its
    transactions after the statement date (scoped by the owned account)."""
    after = datetime.combine(statement.statement_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    card_transactions = db.query(Transaction).filter(
        Transaction.account_id == account.id, Transaction.transaction_date >= after,
    ).all()
    return statement_position(statement, credit_owed(account), card_transactions)


def current_positions(db: Session, user, accounts) -> dict:
    """{account id: StatementPosition} for each of these accounts that has a
    statement (its current one)."""
    latest = (
        db.query(CardStatement.account_id, func.max(CardStatement.statement_date).label("statement_date"))
        .filter(CardStatement.user_id == user.id)
        .group_by(CardStatement.account_id)
        .subquery()
    )
    rows = db.query(CardStatement).join(
        latest,
        (CardStatement.account_id == latest.c.account_id) & (CardStatement.statement_date == latest.c.statement_date),
    ).filter(CardStatement.user_id == user.id).all()
    by_card: dict = {}
    for statement in rows:
        by_card.setdefault(statement.account_id, []).append(statement)
    return {
        acc.id: position_for(db, acc, current_statement(by_card[acc.id]))
        for acc in accounts if acc.id in by_card
    }


MAX_DAYS_TO_DUE = 60
MAX_STATEMENT_AGE_DAYS = 400  # a little over a year of statements


def check_statement(
    statement_balance, statement_date: date, due_date: date, minimum_due, today: date, *, new_date: bool = True,
) -> None:
    """Rules that need today or the whole statement (S-5). Raises ValueError
    with a message the user can act on. The age limit applies only to a
    statement date the user sends (`new_date`), so an old statement that has
    aged past it stays editable."""
    if statement_date > today:
        raise ValueError("The statement date can't be in the future.")
    if new_date and statement_date < today - timedelta(days=MAX_STATEMENT_AGE_DAYS):
        raise ValueError("The statement date can't be more than 400 days ago.")
    if not statement_date <= due_date <= statement_date + timedelta(days=MAX_DAYS_TO_DUE):
        raise ValueError("The due date must be on or after the statement date, and no more than 60 days after it.")
    if minimum_due is not None and _d(minimum_due) > _d(statement_balance):
        raise ValueError("The minimum payment can't be more than the statement balance.")
