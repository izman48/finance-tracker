"""Balance forecast: project the spending-account balance across a horizon."""
from __future__ import annotations

import calendar
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    AccountRole,
    CommitmentDirection,
    CommitmentRule,
    CommitmentStatus,
    PlannedItem,
)

from .cadence import commitment_occurrences
from .commitments import next_payday
from .common import _d, _load, _today, resolve_roles
from .planned import planned_events
from .repayments import repayment_events


def _horizon_end(db: Session, user, horizon: str, today: date) -> date:
    """Resolve a horizon keyword to an end date.

    Accepts `payday`, `month`, or any number of days (e.g. 30, 90, 180, 365),
    capped at 730 days.
    """
    if horizon == "payday":
        payday = next_payday(db, user, today + timedelta(days=1))
        return payday or (today + timedelta(days=30))
    if horizon == "month":
        return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    if str(horizon).isdigit():
        return today + timedelta(days=min(int(horizon), 730))
    return today + timedelta(days=30)


def _floor(setting) -> Decimal:
    """Lowest balance an account may reach: -|overdraft limit|, or £0 with none.

    Sign-agnostic because providers report the limit as either a positive or a
    negative number. A missing limit is a £0 floor, never "unlimited".
    """
    limit = setting.overdraft_limit if setting else None
    return -abs(_d(limit))


def _unassigned_target(spending: list) -> uuid.UUID | None:
    """Spending account that takes events with no account of their own.

    A heuristic: the highest starting balance (where pay usually lands), ties
    broken by id so the choice is stable. None when there is no spending account.
    """
    if not spending:
        return None
    best = min(spending, key=lambda a: (-_d(a.current_balance), str(a.id)))
    return best.id


def _account_breaches(
    spending: list, settings: dict, moves: list[tuple], today: date, end: date,
) -> list[dict]:
    """First day each account goes below its own floor ("overdraft"), or below
    £0 while still inside its limit ("zero"). One entry per breaching account."""
    names = {a.id: a.display_name for a in spending}
    balances = {a.id: _d(a.current_balance) for a in spending}
    floors = {a.id: _floor(settings.get(a.id)) for a in spending}
    if None in {acc for _, acc, _ in moves}:
        names[None], balances[None], floors[None] = None, Decimal(0), Decimal(0)

    by_day: dict[date, list[tuple]] = defaultdict(list)
    for day, acc, amount in moves:
        by_day[day].append((acc, amount))

    first_below: dict[str, dict] = {"overdraft": {}, "zero": {}}
    running = dict(balances)
    day = today
    while day < end:
        day += timedelta(days=1)
        for acc, amount in by_day.get(day, []):
            running[acc] += amount
        for acc, bal in running.items():
            if bal < floors[acc]:
                first_below["overdraft"].setdefault(acc, (day, bal))
            if bal < 0:
                first_below["zero"].setdefault(acc, (day, bal))

    out = []
    for acc in running:
        kind = "overdraft" if acc in first_below["overdraft"] else "zero"
        if acc not in first_below[kind]:
            continue
        when, bal = first_below[kind][acc]
        out.append({
            "account_id": str(acc) if acc is not None else None,
            "account_name": names[acc],
            "date": when,
            "balance": bal,
            "floor": floors[acc],
            "kind": kind,
        })
    out.sort(key=lambda b: (b["date"], b["account_id"] or ""))
    return out


def get_forecast(db: Session, user, horizon: str = "payday") -> dict:
    """Project the spending-account balance forward across the horizon.

    Applies confirmed recurring income/expenses, credit-card repayments and
    planned items as dated movements, producing a daily running-balance
    timeline (all spending accounts pooled) plus the lowest point.

    Breaches are checked both pooled (as before) and per account against each
    account's own floor. Each movement lands on its own spending account
    (commitment/planned `account_id`, card `pay_from_account_id`); one with no
    spending account is attributed to `unassigned_attributed_to` (a heuristic).
    """
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()
    end = _horizon_end(db, user, horizon, today)

    spending = [a for a in accounts if roles[a.id] == AccountRole.SPENDING]
    spending_ids = {a.id for a in spending}
    fallback = _unassigned_target(spending)

    def target(account_id):
        return account_id if account_id in spending_ids else fallback

    start_balance = sum((_d(a.current_balance) for a in spending), Decimal(0))
    overdraft_limit = sum((-_floor(settings.get(a.id)) for a in spending), Decimal(0))

    # Collect signed, dated events within (today, end], and the account each hits.
    events_by_day: dict[date, list[dict]] = defaultdict(list)
    moves: list[tuple] = []

    def add(day: date, account_id, event: dict) -> None:
        events_by_day[day].append(event)
        moves.append((day, target(account_id), event["amount"]))

    confirmed = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    for rule in confirmed:
        sign = Decimal(1) if rule.direction == CommitmentDirection.INCOME.value else Decimal(-1)
        for occ in commitment_occurrences(rule, today + timedelta(days=1), end):
            add(occ, rule.account_id, {
                "label": rule.label,
                "amount": sign * _d(rule.amount),
                "kind": rule.direction,
            })
    for r in repayment_events(db, user, today + timedelta(days=1), end):
        card_setting = settings.get(uuid.UUID(r["account_id"]))
        pay_from = card_setting.pay_from_account_id if card_setting else None
        add(r["due_date"], pay_from,
            {"label": r["label"], "amount": -_d(r["amount"]), "kind": "repayment"})
    planned = (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == user.id, PlannedItem.active.is_(True))
        .all()
    )
    for item in planned:
        for occ_date, amount in planned_events(item, today + timedelta(days=1), end):
            add(occ_date, item.account_id,
                {"label": item.name, "amount": amount, "kind": "planned"})

    # Walk day by day, accumulating the pooled running balance.
    timeline: list[dict] = [{"date": today, "balance": start_balance, "events": []}]
    balance = start_balance
    min_balance, min_date = start_balance, today
    day = today
    while day < end:
        day += timedelta(days=1)
        day_events = events_by_day.get(day, [])
        for ev in day_events:
            balance += ev["amount"]
        timeline.append({"date": day, "balance": balance, "events": day_events})
        if balance < min_balance:
            min_balance, min_date = balance, day

    breaches = []
    if min_balance < 0:
        breaches.append("zero")
    if overdraft_limit > 0 and min_balance < -overdraft_limit:
        breaches.append("overdraft")
    account_breaches = _account_breaches(spending, settings, moves, today, end)
    for b in account_breaches:
        if b["kind"] not in breaches:
            breaches.append(b["kind"])

    return {
        "horizon": horizon,
        "horizon_end": end,
        "start_balance": start_balance,
        "end_balance": balance,
        "min_balance": min_balance,
        "min_date": min_date,
        "overdraft_limit": overdraft_limit,
        "breaches": breaches,
        "account_breaches": account_breaches,
        "unassigned_attributed_to": str(fallback) if fallback is not None else None,
        "timeline": timeline,
    }
