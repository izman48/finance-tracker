"""Balance forecast: project the spending-account balance across a horizon."""
from __future__ import annotations

import calendar
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


def get_forecast(db: Session, user, horizon: str = "payday") -> dict:
    """Project the spending-account balance forward across the horizon.

    Applies confirmed recurring income/expenses and credit-card repayments as
    dated movements, producing a daily running-balance timeline plus the lowest
    point and any breach of the £0 / overdraft lines.
    """
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()
    end = _horizon_end(db, user, horizon, today)

    start_balance = sum(
        (_d(a.current_balance) for a in accounts if roles[a.id] == AccountRole.SPENDING),
        Decimal(0),
    )
    overdraft_limit = sum(
        (_d(settings[a.id].overdraft_limit) for a in accounts
         if roles[a.id] == AccountRole.SPENDING and a.id in settings and settings[a.id].overdraft_limit),
        Decimal(0),
    )

    # Collect signed, dated events within (today, end].
    events_by_day: dict[date, list[dict]] = defaultdict(list)
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
            events_by_day[occ].append(
                {
                    "label": rule.label,
                    "amount": sign * _d(rule.amount),
                    "kind": rule.direction,
                }
            )
    for r in repayment_events(db, user, today + timedelta(days=1), end):
        events_by_day[r["due_date"]].append(
            {"label": r["label"], "amount": -_d(r["amount"]), "kind": "repayment"}
        )
    planned = (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == user.id, PlannedItem.active.is_(True))
        .all()
    )
    for item in planned:
        for occ_date, amount in planned_events(item, today + timedelta(days=1), end):
            events_by_day[occ_date].append(
                {"label": item.name, "amount": amount, "kind": "planned"}
            )

    # Walk day by day, accumulating the running balance.
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

    return {
        "horizon": horizon,
        "horizon_end": end,
        "start_balance": start_balance,
        "end_balance": balance,
        "min_balance": min_balance,
        "min_date": min_date,
        "overdraft_limit": overdraft_limit,
        "breaches": breaches,
        "timeline": timeline,
    }
