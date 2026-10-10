"""Recurring income that hasn't arrived (T-08-10).

A confirmed income commitment is late when its latest expected date is more
than GRACE_DAYS past and no credit matched to it has landed since a week
before that date. Late income is shown (flagged on the commitment and listed
in the forecast) but never counted: it adds nothing to the balance line,
safe-to-spend, savable or projections, which already only count future
occurrences. This module only makes the miss visible.

The expected date is worked back from `next_date` by cadence, never read as
"next_date < today": `sync_suggestions` advances a past next_date, which
would otherwise hide the miss. It stays flagged for one cadence window, until
the next expected date takes over.

Only a credit whose merchant key matches the commitment (its match_key, or
its label's key) and whose amount is within max(GBP 1, 2%) of the expected
amount clears it: a stray GBP 5 from the payer doesn't hide a missing
GBP 1,000. Internal transfer legs never do: money moved in
from your own savings isn't the income. Recomputed on every read, with the
user's key.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, CommitmentDirection, CommitmentRule, CommitmentStatus, Transaction

from .cadence import _step, _step_back
from .commitments import _match_key, transaction_match_key
from .common import _d, _load, resolve_roles
from .planned_matching import tolerance

GRACE_DAYS = 3
EARLY_DAYS = 7  # a payment this many days early still counts


@dataclass(frozen=True)
class LateIncome:
    commitment_id: uuid.UUID
    label: str
    amount: Decimal
    expected_date: date


def last_expected(rule: CommitmentRule, today: date) -> date:
    """The latest occurrence on or before today, whatever next_date says."""
    step = (rule.cadence, rule.interval_days, rule.interval_months)
    d = rule.next_date
    guard = 0
    while d > today and guard < 600:
        d = _step_back(d, *step)
        guard += 1
    while _step(d, *step) <= today and guard < 1200:
        d = _step(d, *step)
        guard += 1
    return d


def late_incomes(db: Session, user, today: date) -> dict[uuid.UUID, LateIncome]:
    rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    candidates = []
    for rule in rules:
        expected = last_expected(rule, today)
        created = rule.created_at.date() if rule.created_at else expected
        if today - expected > timedelta(days=GRACE_DAYS) and created <= expected:
            candidates.append((rule, expected))
    if not candidates:
        return {}
    credits = _real_credits(db, user, min(e for _, e in candidates) - timedelta(days=EARLY_DAYS))
    out = {}
    for rule, expected in candidates:
        keys = {k for k in (rule.match_key, _match_key(rule.direction, rule.label)) if k}
        amount = _d(rule.amount)
        allowed = tolerance(amount)  # the same rule as planned items (T-08-7)
        arrived = any(
            key in keys and day >= expected - timedelta(days=EARLY_DAYS) and abs(paid - amount) <= allowed
            for key, day, paid in credits
        )
        if not arrived:
            out[rule.id] = LateIncome(rule.id, rule.label, amount, expected)
    return out


def _real_credits(db: Session, user, since: date) -> list[tuple[str, date, Decimal]]:
    """(merchant key, date, amount) of real credits since `since` (internal
    transfer legs and card settlements excluded)."""
    from .spending import classify_noise

    txns = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.transaction_date >= datetime.combine(since - timedelta(days=2), time.min, timezone.utc),
        )
        .all()
    )
    accounts, settings = _load(db, user)
    noise = classify_noise(txns, resolve_roles(accounts, settings))
    return [
        (transaction_match_key(tx), tx.transaction_date.date(), _d(tx.amount))
        for tx in txns
        if tx.transaction_type == "credit" and tx.id not in noise and tx.transaction_date.date() >= since
    ]
