"""Settling one-off planned items against the transactions that pay them (T-08-7).

Recomputed on every read, with the user's key (amounts and descriptions are
encrypted), never in a background job and never stored: delete the
transaction, or mark it a transfer, and the planned item comes back.

A transaction settles a one-off planned item when it goes the same way
(expense <- debit, income <- credit), lands within MATCH_DAYS of the planned
date, is within max(GBP 1, 2%) of the planned amount, and is real money: not
an internal transfer leg, not a card repayment, not a purchase moved to a
payment plan, and not already a confirmed commitment's payment. Each
transaction settles at most one item (one-to-one), soonest item first.

What an unsettled item means is fail safe (see `planned_state`): an expense
stays due, even after its date; an income is expected only until its date +
LATE_AFTER_DAYS, then it is late and no longer counted as money coming.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, PlannedItem, PlannedKind, Transaction

from .commitments import commitment_match_keys, transaction_match_key
from .common import _d, _load, resolve_roles

MATCH_DAYS = 7
LATE_AFTER_DAYS = 7
# How far back a one-off item is still looked at: an unpaid expense stays due
# for this long after its date, then it is treated as stale and dropped.
LOOKBACK_DAYS = 60
TOLERANCE_FLOOR = Decimal("1.00")
TOLERANCE_SHARE = Decimal("0.02")


@dataclass(frozen=True)
class PlannedState:
    matched_transaction_id: uuid.UUID | None
    late: bool  # income only: unsettled past its date + LATE_AFTER_DAYS
    counted: bool  # whether it still counts as money in or out


def tolerance(amount: Decimal) -> Decimal:
    return max(TOLERANCE_FLOOR, (amount * TOLERANCE_SHARE).quantize(Decimal("0.01")))


def planned_states(db: Session, user, items: list[PlannedItem], today: date) -> dict[uuid.UUID, PlannedState]:
    """{one-off item id: state}. Recurring and plan items aren't matched."""
    one_offs = [
        i for i in items
        if i.kind == PlannedKind.ONE_OFF.value and i.start_date >= today - timedelta(days=LOOKBACK_DAYS)
    ]
    matches = _match(db, user, one_offs, today) if one_offs else {}
    states = {}
    for item in items:
        if item.kind != PlannedKind.ONE_OFF.value:
            continue
        matched = matches.get(item.id)
        stale = item.start_date < today - timedelta(days=LOOKBACK_DAYS)
        late = (
            item.direction == "income" and matched is None
            and today > item.start_date + timedelta(days=LATE_AFTER_DAYS)
        )
        states[item.id] = PlannedState(matched, late and not stale, matched is None and not late and not stale)
    return states


def _match(db: Session, user, items: list[PlannedItem], today: date) -> dict[uuid.UUID, uuid.UUID]:
    start = min(i.start_date for i in items) - timedelta(days=MATCH_DAYS + 2)  # +2: transfer pairing
    txns = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.transaction_date >= datetime.combine(start, time.min, timezone.utc),
        )
        .all()
    )
    eligible = _real_money(db, user, txns)
    used: set = set()
    out: dict = {}
    for item in sorted(items, key=lambda i: (i.start_date, str(i.id))):
        want = "credit" if item.direction == "income" else "debit"
        amount = _d(item.amount)
        best = None
        for tx in eligible:
            if tx.id in used or tx.transaction_type != want:
                continue
            gap = abs((tx.transaction_date.date() - item.start_date).days)
            if gap > MATCH_DAYS or abs(_d(tx.amount) - amount) > tolerance(amount):
                continue
            key = (gap, abs(_d(tx.amount) - amount), str(tx.id))
            if best is None or key < best[0]:
                best = (key, tx)
        if best is not None:
            used.add(best[1].id)
            out[item.id] = best[1].id
    return out


def _real_money(db: Session, user, txns: list[Transaction]) -> list[Transaction]:
    """Transactions that can settle a planned item: the same exclusions the
    spending figures use, so moving money between your own accounts or paying
    a card never 'pays' a planned bill."""
    from .spending import classify_noise, financed_transaction_ids

    accounts, settings = _load(db, user)
    noise = classify_noise(txns, resolve_roles(accounts, settings))
    financed = financed_transaction_ids(db, user)
    commitment_keys = commitment_match_keys(db, user)
    return [
        tx for tx in txns
        if tx.id not in noise and tx.id not in financed
        and transaction_match_key(tx) not in commitment_keys
    ]
