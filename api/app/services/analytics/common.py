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
