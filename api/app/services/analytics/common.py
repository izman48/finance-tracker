"""Shared helpers for the analytics package: dates, decimals, account roles."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, AccountRole, AccountSetting, AccountType

_DEFAULT_ROLE_BY_TYPE = {
    AccountType.TRANSACTION: AccountRole.SPENDING,
    AccountType.SAVINGS: AccountRole.SAVINGS,
    AccountType.CREDIT_CARD: AccountRole.CREDIT,
    # Loans and mortgages are money owed, so they belong in net worth as
    # liabilities rather than being invisible. They only generate scheduled
    # repayments once the user configures one (repayment_events requires an
    # AccountSetting), so defaulting them here can't put a whole mortgage
    # balance into the forecast as a single payment.
    AccountType.LOAN: AccountRole.CREDIT,
    AccountType.MORTGAGE: AccountRole.CREDIT,
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def default_role(account: Account) -> AccountRole:
    """Role to assume when the user hasn't configured the account yet."""
    try:
        atype = AccountType(account.account_type)
    except ValueError:
        return AccountRole.EXCLUDED
    return _DEFAULT_ROLE_BY_TYPE.get(atype, AccountRole.EXCLUDED)


def resolve_roles(
    accounts: list[Account], settings: dict,
) -> dict:
    """Map account_id -> AccountRole, using settings then type defaults."""
    roles: dict = {}
    for acc in accounts:
        setting = settings.get(acc.id)
        roles[acc.id] = AccountRole(setting.role) if setting else default_role(acc)
    return roles


def _load(db: Session, user):
    accounts = db.query(Account).filter(Account.user_id == user.id).all()
    settings = {
        s.account_id: s
        for s in db.query(AccountSetting).filter(AccountSetting.user_id == user.id).all()
    }
    return accounts, settings


# --- transfers and card settlements ------------------------------------------ #
# Lives here rather than in spending.py because commitment detection needs it
# too, and spending.py already imports from commitments.py (a cycle otherwise).

# Descriptions that indicate a transfer to settle a credit card (not new spend).
CARD_PAYMENT_INDICATORS = (
    # "american exp", not "american express": banks truncate the descriptor to
    # fit a reference, so a real Amex settlement arrives as
    # "AMERICAN EXP 3773 PB945227708021965 FT" and the full word never matches.
    # The prefix still covers the untruncated form.
    "american exp", "amex", "monzo flex", "barclaycard",
    "credit card", "cc payment", "card payment",
)


def detect_internal_transfers(txns: list) -> set:
    """IDs of debit/credit pairs that look like money moving between own accounts."""
    excluded: set = set()
    ordered = sorted(txns, key=lambda t: t.transaction_date)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if (b.transaction_date - a.transaction_date).days > 2:
                break
            if a.account_id == b.account_id:
                continue
            if abs(_d(a.amount) - _d(b.amount)) > Decimal("0.01"):
                continue
            if {a.transaction_type, b.transaction_type} == {"debit", "credit"}:
                excluded.add(a.id)
                excluded.add(b.id)
    return excluded


def is_card_settlement(tx, role: AccountRole | None) -> bool:
    """True if this transaction is paying a credit card off, either leg.

    Card settlements are already modelled as repayment events (derived from the
    card's balance and repayment settings), so counting them anywhere else —
    as spending, or as a detected commitment — double-counts the same money.
    """
    if role == AccountRole.CREDIT and tx.transaction_type == "credit":
        return True  # money arriving to settle the card
    if role != AccountRole.CREDIT and tx.transaction_type == "debit":
        desc = f"{tx.description or ''} {tx.merchant_name or ''}".lower()
        return any(ind in desc for ind in CARD_PAYMENT_INDICATORS)
    return False
