"""Warnings about a card's repayment settings (T-10-5; ux A1, A.6).

Each is a code plus string values; the UI words them from fixed templates.
They describe the card's next repayment exactly as the forecast plans it
(`repayment_events`), so a warning can't disagree with the forecast. While a
commitment is tied to the card there are none (the forecast may pay that
bill instead):

- interest_cost: the next payment is less than what is still due on the
  statement, so the card charges interest. With an APR (effective yearly
  rate, as UK lenders quote it) the estimate is the unpaid part times the
  monthly rate, (1 + APR)^(1/12) - 1; without one there is no figure.
- late_fee_risk: the next payment falls after the statement's due date.
- overdraft_breach: the forecast takes the pay-from account past its
  overdraft limit (or below £0 with none) by the payment date.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import Account, AccountRole, AccountSetting, CommitmentRule, CommitmentStatus

from .common import _today, account_role
from .forecast import get_forecast
from .repayments import cards_with_linked_bills, repayment_events
from .statements import current_positions

PENNY = Decimal("0.01")
REACH = timedelta(days=400)


def _money(value) -> str:
    return str(Decimal(str(value)).quantize(PENNY, rounding=ROUND_HALF_UP))


def card_warnings(db: Session, user, account: Account, setting: AccountSetting | None) -> list[dict]:
    """The warnings for this account's saved repayment settings ([] for an
    account that isn't a credit card or has no repayment planned)."""
    if setting is None or account_role(account, setting) != AccountRole.CREDIT:
        return []
    today = _today()
    if _has_linked_bill(db, user, account, today):
        return []
    events = [r for r in repayment_events(db, user, today, today + REACH) if r["account_id"] == str(account.id)]
    if not events:
        return []
    payment = events[0]
    position = current_positions(db, user, [account]).get(account.id)
    warnings: list[dict] = []
    if position is not None and not position.paid and position.statement.due_date >= today:
        if payment["amount"] < position.amount_still_due:
            warnings.append(_interest(position.amount_still_due - payment["amount"], setting.card_apr))
        if payment["due_date"] > position.statement.due_date:
            warnings.append({"code": "late_fee_risk", "values": {
                "pay_date": payment["due_date"].isoformat(),
                "due_date": position.statement.due_date.isoformat(),
                "repayment_day": str(setting.repayment_day) if setting.repayment_cadence == "monthly" else None,
            }})
    breach = _overdraft(db, user, setting, payment, today)
    if breach is not None:
        warnings.append(breach)
    return warnings


def _has_linked_bill(db: Session, user, account: Account, today: date) -> bool:
    """A confirmed commitment is tied to this card, so the forecast may pay
    that bill instead of the repayment (eng-b on #188; the same rule hides
    next_payment). A warning would then describe a payment that isn't
    planned, so there are none."""
    confirmed = db.query(CommitmentRule).filter(
        CommitmentRule.user_id == user.id, CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
    ).all()
    return str(account.id) in cards_with_linked_bills(db, user, confirmed, today)


def _interest(unpaid: Decimal, apr) -> dict:
    if apr is None:
        return {"code": "interest_cost", "values": {"monthly_interest": None, "apr": None}}
    monthly_rate = (1 + Decimal(str(apr)) / 100) ** (Decimal(1) / 12) - 1
    return {"code": "interest_cost", "values": {
        "monthly_interest": _money(unpaid * monthly_rate), "apr": _money(apr),
    }}


def _overdraft(db: Session, user, setting: AccountSetting, payment: dict, today: date) -> dict | None:
    """The forecast's own breach on the pay-from account, by the payment date."""
    days = (payment["due_date"] - today).days
    if setting.pay_from_account_id is None or days < 1:
        return None
    forecast = get_forecast(db, user, horizon=str(days))
    pay_from = str(setting.pay_from_account_id)
    breach = next((b for b in forecast["account_breaches"] if b["account_id"] == pay_from), None)
    if breach is None or breach["date"] > payment["due_date"]:
        return None
    floor = Decimal(str(breach["floor"]))
    return {"code": "overdraft_breach", "values": {
        "amount": _money(payment["amount"]),
        "account_name": breach["account_name"],
        "balance": _money(breach["balance"]),
        "limit": _money(-floor) if floor < 0 else None,
        "date": payment["due_date"].isoformat(),
    }}
