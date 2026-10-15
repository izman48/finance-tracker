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
    RepaymentStrategy,
)

from .cadence import commitment_occurrences
from . import card_payments
from .commitments import committed_window_end, next_payday, payday_dates
from app.services.balance_sign import credit_owed as credit_owed_for

from .common import _d, _load, _today, resolve_roles
from app.services.holdings import listing as holdings_listing

from .net_worth import assets_total, liabilities_total, total_owed
from .planned import planned_events
from .planned_matching import planned_states
from app.services.claude_keep import claude_rows, counted_commitments, held_back, held_removed_planned
from .repayments import repayment_events, scheduled_outflows
from .statements import current_positions


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
    # Cut at payday like the forecast, so a bill due on payday is its own
    # window (eng-b on #234).
    window_paydays = payday_dates(db, user, today, window_end)
    committed = _money_out(db, user, expense_to_payday, planned, states, today, window_end, window_paydays)
    committed_as_is = _money_out(db, user, expense_now, active_planned, states, today, window_end, window_paydays)
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
    out_30 = _money_out(db, user, expense_30, planned, states, today, horizon,
                        paydays=payday_dates(db, user, today, horizon))
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
        # Investment kinds only (owner D1), as net worth's Investments (T-11-7).
        "investments_total": holdings_listing.investments_total(db, user),
        "total_owed": total_owed(credit_owed, liabilities),
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
        "accounts": _accounts(db, user, accounts, roles, settings, today),
    }


def _money_out(db: Session, user, expense_rules: list, planned: list, states: dict, start, end,
               paydays: list | None = None) -> Decimal:
    """Bills, card repayments and planned expenses in [start, end]. A planned
    item flagged as a card payment counts once with the projected card
    repayments: in each pay window, the larger of the two (T-12-4a)."""
    occurrences, repayments = scheduled_outflows(db, user, expense_rules, start, end)
    due = _planned_occurrences(planned, states, start, end)
    flagged = [o for o in due if o[0].is_card_payment]
    other = sum((a for item, _, a in due if not item.is_card_payment), Decimal(0))
    kept_card, kept_repayments, _ = card_payments.resolve(
        card_payments.pay_windows(start, end, paydays or []), flagged, repayments,
    )
    return (
        sum((_d(rule.amount) for rule, _ in occurrences), Decimal(0))
        + sum((r["amount"] for r in kept_repayments), Decimal(0))
        + other
        + sum((a for _, _, a in kept_card), Decimal(0))
    )


def _planned_occurrences(planned: list, states: dict, start, end) -> list[tuple]:
    """(item, date, amount > 0) for each planned expense due in [start, end],
    (a one-off already paid is left out; one overdue and unpaid is still due)."""
    out = []
    for item in planned:
        if item.direction == "income":
            continue
        state = states.get(item.id)
        if state is None:  # recurring / payment plan: by schedule
            out.extend((item, d, -a) for d, a in planned_events(item, start, end) if a < 0)
        elif state.counted and max(item.start_date, start) <= end:
            out.append((item, max(item.start_date, start), _d(item.amount)))
    return out


def _accounts(db: Session, user, accounts, roles, settings, today) -> list[dict]:
    """Each account's summary; a credit account also carries its current
    statement (the card statements route's position), or None."""
    cards = [acc for acc in accounts if roles[acc.id] == AccountRole.CREDIT]
    positions = current_positions(db, user, cards) if cards else {}
    rows = []
    for acc in accounts:
        row = _account_summary(acc, roles[acc.id], settings.get(acc.id))
        if roles[acc.id] == AccountRole.CREDIT:
            row["statement"] = _statement(positions.get(acc.id), today)
        rows.append(row)
    return rows


def _statement(position, today) -> dict | None:
    """The current statement as the summary shows it (no ids: sec, option A).
    `missing`: its due date has passed and no newer one is entered, as in
    the card statements route."""
    if position is None:
        return None
    statement = position.statement
    return {
        "statement_balance": _d(statement.statement_balance),
        "due_date": statement.due_date,
        "paid": position.paid,
        "missing": statement.due_date < today,
    }


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
        "instalment_card": bool(s and s.instalment_card),
        "repayment_fix_needed": bool(
            s and role == AccountRole.CREDIT and s.repayment_strategy == RepaymentStrategy.SCHEDULED.value
            and not s.instalment_card
        ),
    }
