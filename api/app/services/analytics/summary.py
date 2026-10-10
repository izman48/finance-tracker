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
    PlannedItem,
)

from .cadence import commitment_occurrences
from .commitments import next_payday
from app.services.balance_sign import credit_owed as credit_owed_for

from .common import _d, _load, _today, resolve_roles
from .net_worth import assets_total
from .planned import planned_events
from .planned_matching import planned_states
from .repayments import repayment_events, scheduled_outflows


def get_summary(db: Session, user) -> dict:
    """The dashboard cashflow summary."""
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()

    available_cash = Decimal(0)
    overdraft_cushion = Decimal(0)
    credit_owed = Decimal(0)  # what is owed: cards in credit don't offset it
    credit_in_favour = Decimal(0)  # cards in credit (overpaid): money the user has
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
            owed = credit_owed_for(acc)
            if owed > 0:
                credit_owed += owed
            else:
                credit_in_favour -= owed

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
    planned = (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == user.id, PlannedItem.active.is_(True))
        .all()
    )
    states = planned_states(db, user, planned, today)
    committed = _outflow(db, user, expense_rules, today, window_end) + _planned_out(planned, states, today, window_end)

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
    # Planned income is left out on purpose: it never raises safe-to-spend or
    # savable until the credit lands (owner decision D1; an injected "refund
    # coming" must not unlock spending). It still shows in the forecast.
    out_30 = _outflow(db, user, expense_rules, today, horizon) + _planned_out(planned, states, today, horizon)
    savable = max(Decimal(0), available_cash + income_30 - out_30)

    manual_assets = assets_total(db, user)

    return {
        "available_cash": available_cash,
        "overdraft_cushion": overdraft_cushion,
        "credit_owed": credit_owed,
        "savings_total": savings_total,
        "assets_total": manual_assets,
        "net_worth": available_cash + savings_total + manual_assets + credit_in_favour - credit_owed,
        "committed_before_payday": committed,
        "safe_to_spend": safe_to_spend,
        "savable": savable,
        "next_payday": payday,
        # Show upcoming card repayments over a display horizon, independent of the
        # payday window — so a bill due just after payday is still visible.
        "next_repayments": repayment_events(db, user, today, today + timedelta(days=92)),
        "accounts": [_account_summary(acc, roles[acc.id], settings.get(acc.id)) for acc in accounts],
    }


def _outflow(db: Session, user, expense_rules: list, start, end) -> Decimal:
    """Confirmed bills plus card repayments in [start, end], each card's
    repayment counted once (see scheduled_outflows)."""
    occurrences, repayments = scheduled_outflows(db, user, expense_rules, start, end)
    return (
        sum((_d(rule.amount) for rule, _ in occurrences), Decimal(0))
        + sum((r["amount"] for r in repayments), Decimal(0))
    )


def _planned_out(planned: list, states: dict, start, end) -> Decimal:
    """Planned expenses due in [start, end] (the third source of money out,
    beside commitments and card repayments). Income is never counted here.

    A one-off expense already paid (matched to its transaction) is left out,
    so it isn't counted twice; one that is overdue and unpaid is still due."""
    total = Decimal(0)
    for item in planned:
        if item.direction == "income":
            continue
        state = states.get(item.id)
        if state is None:  # recurring / payment plan: by schedule
            total += sum((-a for _, a in planned_events(item, start, end) if a < 0), Decimal(0))
        elif state.counted and max(item.start_date, start) <= end:
            total += _d(item.amount)
    return total


def _account_summary(acc: Account, role: AccountRole, s: AccountSetting | None) -> dict:
    return {
        "id": str(acc.id),
        "display_name": acc.display_name,
        "provider_name": acc.provider_name,
        "account_type": acc.account_type,
        "role": role.value,
        "current_balance": acc.current_balance,
        "credit_owed": credit_owed_for(acc) if role == AccountRole.CREDIT else None,
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
