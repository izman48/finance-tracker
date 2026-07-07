"""Recurring commitments: detection, match keys, paydays, and transaction conversion."""
from __future__ import annotations

import statistics
import uuid as _uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Account,
    CommitmentDirection,
    CommitmentCadence,
    CommitmentRule,
    CommitmentSource,
    CommitmentStatus,
    PlannedItem,
    PlannedKind,
    Transaction,
)

from .cadence import _cadence_from_interval, _step, _step_back, commitment_occurrences
from .common import _d, _today

# Detection thresholds (mirrors the frontend Bills heuristic).
_MIN_OCCURRENCES = 3
_MAX_INTERVAL_CV = 0.30  # std-dev must be < 30% of the mean interval


def _match_key(direction: str, merchant: str) -> str:
    return f"{direction}:{merchant.strip().lower()}"


def merchant_match_key(direction: str, merchant: str | None) -> str | None:
    """Public: match key for a user-supplied merchant/description, or None if blank.

    Lets a manually-added commitment be tied to the real transactions it should
    exclude, using the same keying as auto-detection.
    """
    if not merchant or not merchant.strip():
        return None
    return _match_key(direction, merchant)


def transaction_match_key(tx: Transaction) -> str:
    """The key a transaction would group under in recurring detection."""
    direction = (
        CommitmentDirection.INCOME.value
        if tx.transaction_type == "credit"
        else CommitmentDirection.EXPENSE.value
    )
    return _match_key(direction, (tx.merchant_name or tx.description or "Unknown").strip())


def commitment_match_keys(db: Session, user) -> set[str]:
    """Match keys of confirmed commitments, for flagging/excluding their transactions.

    Detected commitments carry the match_key they were grouped under; manual ones
    fall back to their label, which catches commitments added from a transaction.
    """
    rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    keys: set[str] = set()
    for r in rules:
        if r.match_key:
            keys.add(r.match_key)
        keys.add(_match_key(r.direction, r.label))
    return keys


def detect_recurring(db: Session, user) -> list[dict]:
    """Detect recurring income (credits) and expenses (debits) from history."""
    txns = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user.id)
        .all()
    )

    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for tx in txns:
        direction = (
            CommitmentDirection.INCOME.value
            if tx.transaction_type == "credit"
            else CommitmentDirection.EXPENSE.value
        )
        merchant = (tx.merchant_name or tx.description or "Unknown").strip()
        groups[(direction, merchant)].append(tx)

    candidates: list[dict] = []
    for (direction, merchant), group in groups.items():
        if len(group) < _MIN_OCCURRENCES:
            continue
        group.sort(key=lambda t: t.transaction_date)
        intervals = [
            (group[i].transaction_date - group[i - 1].transaction_date).days
            for i in range(1, len(group))
        ]
        intervals = [iv for iv in intervals if iv > 0]
        if len(intervals) < 2:
            continue
        mean = statistics.mean(intervals)
        if mean <= 0:
            continue
        stdev = statistics.pstdev(intervals)
        if stdev > mean * _MAX_INTERVAL_CV:
            continue  # not consistent enough to be "recurring"

        avg_amount = sum((_d(t.amount) for t in group), Decimal(0)) / len(group)
        last_date = group[-1].transaction_date.date()
        cadence, interval_days, interval_months = _cadence_from_interval(mean)

        # If the next expected occurrence is well overdue, the pattern has
        # probably stopped (cancelled sub, ended salary) — don't suggest it.
        today = _today()
        if (today - last_date).days > mean * 2 + 7:
            continue

        # Otherwise surface the first occurrence that is still ahead of us.
        next_date = _step(last_date, cadence, interval_days, interval_months)
        guard = 0
        while next_date < today and guard < 600:
            next_date = _step(next_date, cadence, interval_days, interval_months)
            guard += 1

        candidates.append(
            {
                "direction": direction,
                "label": merchant,
                "amount": avg_amount.quantize(Decimal("0.01")),
                "cadence": cadence,
                "interval_days": interval_days,
                "interval_months": interval_months,
                "next_date": next_date,
                "match_key": _match_key(direction, merchant),
            }
        )
    return candidates


def commitment_from_transaction(db: Session, user, transaction_id: str, cadence: str = "monthly"):
    """Create (or confirm) a recurring commitment derived from a transaction.

    Uses the same match_key as auto-detection so it dedupes with any suggestion
    for the same merchant rather than creating a duplicate.
    """
    try:
        tid = transaction_id if isinstance(transaction_id, _uuid.UUID) else _uuid.UUID(str(transaction_id))
    except (ValueError, AttributeError):
        return None
    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == tid, Account.user_id == user.id)
        .first()
    )
    if not tx:
        return None

    direction = (
        CommitmentDirection.INCOME.value
        if tx.transaction_type == "credit"
        else CommitmentDirection.EXPENSE.value
    )
    label = (tx.merchant_name or tx.description or "Recurring").strip()
    # "yearly" is an alias clients may send — stored as every-12-months.
    if cadence == "yearly":
        cadence = CommitmentCadence.EVERY_N_MONTHS.value
        interval_months = 12
    else:
        interval_months = 3 if cadence == CommitmentCadence.EVERY_N_MONTHS.value else None

    # Next occurrence: step from the transaction date forward until it's in the future.
    d = tx.transaction_date.date()
    today = _today()
    guard = 0
    while d <= today and guard < 600:
        d = _step(d, cadence, None, interval_months)
        guard += 1

    key = _match_key(direction, label)
    # match_key is encrypted at rest — dedupe against the user's rules in Python.
    rule = next(
        (
            r
            for r in db.query(CommitmentRule).filter(CommitmentRule.user_id == user.id)
            if r.match_key == key
        ),
        None,
    )
    if rule:
        rule.status = CommitmentStatus.CONFIRMED.value
        rule.amount = _d(tx.amount)
        rule.cadence = cadence
        rule.interval_months = interval_months
        rule.next_date = d
    else:
        rule = CommitmentRule(
            user_id=user.id,
            direction=direction,
            label=label,
            amount=_d(tx.amount),
            cadence=cadence,
            interval_months=interval_months,
            next_date=d,
            source=CommitmentSource.MANUAL.value,
            status=CommitmentStatus.CONFIRMED.value,
            match_key=key,
        )
        db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def convert_transaction_to_plan(
    db: Session, user, transaction_id: str, months: int, monthly_amount, start_date: date
):
    """Convert a purchase into a payment plan: pay `monthly_amount` for `months`.

    The original transaction is linked so spending drops the lump (the installments
    show in the forecast instead). Re-converting the same transaction updates the
    existing plan rather than duplicating it.
    """
    try:
        tid = transaction_id if isinstance(transaction_id, _uuid.UUID) else _uuid.UUID(str(transaction_id))
    except (ValueError, AttributeError):
        return None
    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == tid, Account.user_id == user.id)
        .first()
    )
    if not tx:
        return None

    months = max(1, int(months))
    monthly = _d(monthly_amount)
    total = (monthly * months).quantize(Decimal("0.01"))
    name = (tx.merchant_name or tx.description or "Payment plan").strip()

    item = (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == user.id, PlannedItem.source_transaction_id == tx.id)
        .first()
    )
    if item:
        item.name = name
        item.kind = PlannedKind.INSTALLMENT_PLAN.value
        item.direction = CommitmentDirection.EXPENSE.value
        item.start_date = start_date
        item.total_amount = total
        item.installments = months
        item.cadence = "monthly"
        item.account_id = tx.account_id
        item.active = True
    else:
        item = PlannedItem(
            user_id=user.id,
            name=name,
            direction=CommitmentDirection.EXPENSE.value,
            kind=PlannedKind.INSTALLMENT_PLAN.value,
            start_date=start_date,
            total_amount=total,
            installments=months,
            cadence="monthly",
            account_id=tx.account_id,
            source_transaction_id=tx.id,
        )
        db.add(item)
    db.commit()
    db.refresh(item)
    return item


def sync_suggestions(db: Session, user) -> None:
    """Persist newly-detected commitments as `suggested`, without touching ones
    the user has already confirmed or dismissed."""
    existing_rules = db.query(CommitmentRule).filter(CommitmentRule.user_id == user.id).all()
    existing_keys = {rule.match_key for rule in existing_rules if rule.match_key}

    # Maintenance: advance stale next_dates so the review list never shows a
    # "next" occurrence in the past. (Forecasting already rolls forward the
    # same way in commitment_occurrences; this just persists it for display.)
    today = _today()
    for rule in existing_rules:
        guard = 0
        while rule.next_date and rule.next_date < today and guard < 600:
            rule.next_date = _step(rule.next_date, rule.cadence, rule.interval_days, rule.interval_months)
            guard += 1

    for cand in detect_recurring(db, user):
        if cand["match_key"] in existing_keys:
            continue
        db.add(
            CommitmentRule(
                user_id=user.id,
                direction=cand["direction"],
                label=cand["label"],
                amount=cand["amount"],
                cadence=cand["cadence"],
                interval_days=cand["interval_days"],
                interval_months=cand["interval_months"],
                next_date=cand["next_date"],
                source=CommitmentSource.DETECTED.value,
                status=CommitmentStatus.SUGGESTED.value,
                match_key=cand["match_key"],
            )
        )
    db.commit()


def skip_commitment(db: Session, user, commitment_id):
    """Skip the next occurrence of a commitment (income or expense) — e.g. it was
    paid early. Advances next_date by one cadence step so this occurrence drops
    out of safe-to-spend, the forecast and coming-up, then resumes normally.
    Returns the updated rule, or None if not found.
    """
    try:
        cid = commitment_id if isinstance(commitment_id, _uuid.UUID) else _uuid.UUID(str(commitment_id))
    except (ValueError, AttributeError):
        return None
    rule = (
        db.query(CommitmentRule)
        .filter(CommitmentRule.id == cid, CommitmentRule.user_id == user.id)
        .first()
    )
    if not rule or not rule.next_date:
        return None
    rule.next_date = _step(rule.next_date, rule.cadence, rule.interval_days, rule.interval_months)
    db.commit()
    db.refresh(rule)
    return rule


def next_payday(db: Session, user, from_date: date) -> date | None:
    """Next confirmed income date on/after from_date."""
    incomes = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    dates = [occ for r in incomes for occ in commitment_occurrences(r, from_date, from_date + timedelta(days=400))]
    return min(dates) if dates else None


def last_payday(db: Session, user, today: date) -> date | None:
    """Most recent confirmed income date on/before today (steps back from next_date)."""
    incomes = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    best: date | None = None
    for r in incomes:
        d = r.next_date
        guard = 0
        while d > today and guard < 600:
            d = _step_back(d, r.cadence, r.interval_days, r.interval_months)
            guard += 1
        if d <= today and (best is None or d > best):
            best = d
    return best
