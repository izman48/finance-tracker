"""The dashboard cashflow summary (safe-to-spend and friends)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Account,
    AccountRole,
    AccountSetting,
    CommitmentDirection,
    CommitmentRule,
    CommitmentStatus,
)

from .cadence import commitment_occurrences
from .commitments import next_payday
from .common import _d, _load, _today, resolve_roles
from .net_worth import assets_total
from .repayments import repayment_events


def get_summary(db: Session, user) -> dict:
    """The dashboard cashflow summary."""
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()

    available_cash = Decimal(0)
    overdraft_cushion = Decimal(0)
    credit_owed = Decimal(0)
    savings_total = Decimal(0)
    for acc in accounts:
        role = roles[acc.id]
        if role == AccountRole.SPENDING:
            available_cash += _d(acc.current_balance)
            setting = settings.get(acc.id)
            if setting and setting.overdraft_limit:
                overdraft_cushion += _d(setting.overdraft_limit)
        elif role == AccountRole.SAVINGS:
            savings_total += _d(acc.current_balance)
        elif role == AccountRole.CREDIT:
            credit_owed += abs(_d(acc.current_balance))

    payday = next_payday(db, user, today)
    window_end = payday or (today + timedelta(days=30))

    # Confirmed expense commitments due before the next payday.
    expense_rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.EXPENSE.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    committed = Decimal(0)
    for rule in expense_rules:
        committed += _d(rule.amount) * len(commitment_occurrences(rule, today, window_end))
    repayments = repayment_events(db, user, today, window_end)
    committed += sum((r["amount"] for r in repayments), Decimal(0))

    safe_to_spend = max(Decimal(0), available_cash - committed)

    # Savable: surplus expected to survive a 30-day window (incl. next income).
    horizon = today + timedelta(days=30)
    income_rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    income_30 = sum(
        (_d(r.amount) * len(commitment_occurrences(r, today, horizon)) for r in income_rules),
        Decimal(0),
    )
    expense_30 = sum(
        (_d(r.amount) * len(commitment_occurrences(r, today, horizon)) for r in expense_rules),
        Decimal(0),
    )
    repay_30 = sum((r["amount"] for r in repayment_events(db, user, today, horizon)), Decimal(0))
    savable = max(Decimal(0), available_cash + income_30 - expense_30 - repay_30)

    manual_assets = assets_total(db, user)

    return {
        "available_cash": available_cash,
        "overdraft_cushion": overdraft_cushion,
        "credit_owed": credit_owed,
        "savings_total": savings_total,
        "assets_total": manual_assets,
        "net_worth": available_cash + savings_total + manual_assets - credit_owed,
        "committed_before_payday": committed,
        "safe_to_spend": safe_to_spend,
        "savable": savable,
        "next_payday": payday,
        # Show upcoming card repayments over a display horizon, independent of the
        # payday window — so a bill due just after payday is still visible.
        "next_repayments": repayment_events(db, user, today, today + timedelta(days=92)),
        "accounts": [_account_summary(acc, roles[acc.id], settings.get(acc.id)) for acc in accounts],
    }


def _account_summary(acc: Account, role: AccountRole, s: AccountSetting | None) -> dict:
    return {
        "id": str(acc.id),
        "display_name": acc.display_name,
        "provider_name": acc.provider_name,
        "account_type": acc.account_type,
        "role": role.value,
        "current_balance": acc.current_balance,
        "overdraft_limit": s.overdraft_limit if s else None,
        "repayment_cadence": s.repayment_cadence if s else None,
        "repayment_day": s.repayment_day if s else None,
        "repayment_interval_months": s.repayment_interval_months if s else None,
        "repayment_anchor_date": s.repayment_anchor_date if s else None,
        "repayment_strategy": s.repayment_strategy if s else None,
        "repayment_fixed_amount": s.repayment_fixed_amount if s else None,
        "repayment_installments": s.repayment_installments if s else None,
        "pay_from_account_id": str(s.pay_from_account_id) if s and s.pay_from_account_id else None,
    }
