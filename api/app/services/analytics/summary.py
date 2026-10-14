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
from .commitments import committed_window_end, next_payday
from app.services.balance_sign import credit_owed as credit_owed_for

from .common import _d, _load, _today, resolve_roles
from .net_worth import assets_total, liabilities_total
from .planned import planned_events
from .planned_matching import planned_states
from app.services.claude_keep import claude_rows, counted_commitments, held_back, held_removed_planned
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
    window_end = committed_window_end(db, user, today)

    # Confirmed expense commitments due before the next payday. No Claude
    # change may raise safe-to-spend until the user keeps it (T-08-21b, D5):
    # a bill Claude dismissed, lowered or moved later counts the higher of
    # now and before-Claude; what that holds back is reported for the UI.
    def money_in(start, end):
        return lambda r: _d(r.amount) * len(commitment_occurrences(r, start, end))

    confirmed = CommitmentStatus.CONFIRMED.value
    expense_now = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.EXPENSE.value,
            CommitmentRule.status == confirmed,
        )
        .all()
    )
    expense = CommitmentDirection.EXPENSE.value
    expense_to_payday = counted_commitments(db, user.id, expense, money_in(today, window_end))
    active_planned = (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == user.id, PlannedItem.active.is_(True))
        .all()
    )
    # A planned expense Claude removed still counts until kept (T-08-21b).
    planned = active_planned + held_removed_planned(db, user.id)
    states = planned_states(db, user, planned, today)
    committed = _outflow(db, user, expense_to_payday, today, window_end) + _planned_out(planned, states, today, window_end)
    committed_as_is = (
        _outflow(db, user, expense_now, today, window_end) + _planned_out(active_planned, states, today, window_end)
    )
    safe_pending_keep = max(Decimal(0), committed - committed_as_is)

    safe_to_spend = max(Decimal(0), available_cash - committed)

    # Savable: surplus expected to survive a 30-day window (incl. next income).
    horizon = today + timedelta(days=30)
    income_rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status == confirmed,
        )
        .all()
    )
    # Strict parity (D4): an income Claude raised or confirmed counts as it
    # was before Claude until the user keeps the change (or as it is now, if
    # that's less). The difference is reported so the UI can say so.
    claude = claude_rows(db, user.id, [r.id for r in income_rules])

    def in_window(r) -> Decimal:
        if r.status != confirmed:
            return Decimal(0)
        return _d(r.amount) * len(commitment_occurrences(r, today, horizon))

    income_30 = Decimal(0)
    pending_keep = Decimal(0)
    for r in income_rules:
        now = in_window(r)
        version = held_back(r, claude[r.id], in_window) if r.id in claude else r
        counted = in_window(version) if version is not None else Decimal(0)
        income_30 += counted
        pending_keep += now - counted
    # Planned income is left out on purpose: it never raises safe-to-spend or
    # savable until the credit lands (owner decision D1; an injected "refund
    # coming" must not unlock spending). It still shows in the forecast.
    expense_30 = counted_commitments(db, user.id, expense, money_in(today, horizon))
    out_30 = _outflow(db, user, expense_30, today, horizon) + _planned_out(planned, states, today, horizon)
    savable = max(Decimal(0), available_cash + income_30 - out_30)

    manual_assets = assets_total(db, user)
    liabilities = liabilities_total(db, user)

    return {
        "available_cash": available_cash,
        "overdraft_cushion": overdraft_cushion,
        "credit_owed": credit_owed,
        "savings_total": savings_total,
        "assets_total": manual_assets,
        "liabilities_total": liabilities,
        "net_worth": available_cash + savings_total + manual_assets + credit_in_favour - credit_owed - liabilities,
        "committed_before_payday": committed,
        "safe_to_spend": safe_to_spend,
        "savable": savable,
        "savable_pending_keep_total": pending_keep,
        "safe_to_spend_pending_keep_total": safe_pending_keep,
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
