"""Card statements read from the provider's card balance response (T-10-2).

TrueLayer's card balance can carry `last_statement_balance`,
`last_statement_date`, `payment_due` and `payment_due_date`. nilu already
fetches that response on every sync, so nothing here calls out.

Rules (sec, T-10-2):
- Values are parsed with Decimal(str(v)); the sign goes through balance_sign
  (abs() for providers whose sign isn't verified).
- A value that isn't a number, a missing or bad date, a due date before the
  statement date (or more than 60 days after), a future statement date, or a
  statement that owes nothing stores nothing for that period.
- A response without the fields never deletes or zeroes a stored statement.
- Repeated syncs upsert one provider row per card and statement date; a
  provider write never touches a manual row (manual wins).
- Logs hold field-presence booleans per TrueLayer provider id only: no
  values, dates or ids.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models import Account, CardStatement, StatementSource
from app.schemas import PLANNED_EVENT_MAX_AMOUNT
from app.services.analytics.common import _today
from app.services.analytics.statements import check_statement
from app.services.balance_sign import owed_amount

logger = logging.getLogger(__name__)

STATEMENT_FIELDS = ("last_statement_balance", "last_statement_date", "payment_due", "payment_due_date")
PENNY = Decimal("0.01")


def log_statement_field_coverage(provider_id: str, balance: dict) -> None:
    """Which statement fields this provider fills (booleans only)."""
    present = " ".join(f"{field}={balance.get(field) is not None}" for field in STATEMENT_FIELDS)
    logger.info("Card statement fields from %s: %s", provider_id, present)


def store_provider_statement(db: Session, account: Account, balance: dict) -> None:
    """Upsert the provider statement in this card balance response, if it has
    a valid one. Never commits; the sync does."""
    parsed = _parse(account, balance)
    if parsed is None:
        return
    statement_balance, statement_date, due_date, minimum_due = parsed
    row = db.query(CardStatement).filter(
        CardStatement.user_id == account.user_id,
        CardStatement.account_id == account.id,
        CardStatement.statement_date == statement_date,
        CardStatement.source == StatementSource.PROVIDER.value,
    ).first()
    if row is None:
        row = CardStatement(
            user_id=account.user_id, account_id=account.id, statement_date=statement_date,
            source=StatementSource.PROVIDER.value,
        )
        db.add(row)
    row.statement_balance = statement_balance
    row.due_date = due_date
    row.minimum_due = minimum_due


def _parse(account: Account, balance: dict):
    """(statement balance, statement date, due date, minimum or None), or
    None when the response holds no valid statement."""
    raw = _money(balance.get("last_statement_balance"))
    statement_date = _day(balance.get("last_statement_date"))
    due_date = _day(balance.get("payment_due_date"))
    if raw is None or statement_date is None or due_date is None:
        return None
    statement_balance = owed_amount(account, raw)
    if not PENNY <= statement_balance <= PLANNED_EVENT_MAX_AMOUNT:
        return None
    minimum = _money(balance.get("payment_due"))
    minimum_due = owed_amount(account, minimum) if minimum is not None else None
    if minimum_due is not None and not PENNY <= minimum_due <= statement_balance:
        minimum_due = None  # a bad minimum doesn't throw away a good statement
    try:
        check_statement(statement_balance, statement_date, due_date, minimum_due, _today())
    except ValueError:
        return None
    return statement_balance, statement_date, due_date, minimum_due


def _money(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        return amount.quantize(PENNY) if amount.is_finite() else None
    except InvalidOperation:
        return None


def _day(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None
