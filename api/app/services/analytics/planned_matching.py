"""Settling one-off planned items against the transactions that pay them (T-08-7).

Recomputed on every read, with the user's key (amounts and descriptions are
encrypted), never in a background job and never stored: delete the
transaction, or mark it a transfer, and the planned item comes back.

A transaction settles a one-off planned item when it goes the same way
(expense <- debit, income <- credit), lands within MATCH_DAYS of the planned
date, has the right amount, and is real money. The amount must be exact,
unless the planned name shares a word with the transaction's merchant or
description ("Phone bill" / "VODAFONE PHONE DD"), and then max(GBP 1, 2%)
either way is allowed. So a coincidental GBP 49.50 purchase can't settle a
GBP 50 bill, while "Car insurance" paid to ADMIRAL at exactly the planned
amount still does. Case is ignored, and so are stop-words, company suffixes
and words under 3 letters. Real money means: not
an internal transfer leg, not a card repayment, not a purchase moved to a
payment plan, and not already a confirmed commitment's payment. Each
transaction settles at most one item (one-to-one), soonest item first.

A Claude change to a bill can't free its payment (T-20-1a): while the change
is unkept, a payment is the bill's if the bill as it is now *or* as it was
before Claude matches it (`held_match_rules`), so fewer items settle and
safe-to-spend can't rise. `planned_states` is that held view, used by every
figure and list. What it holds back is not yet in the pending-keep total:
that ships with the "Keep this change" for raises and renames (T-20-1b),
so the app never says a change is waiting for a keep it can't take.

What an unsettled item means is fail safe (see `planned_states`): an expense
stays due, even long after its date, until it is paid or removed (past
OVERDUE_AFTER_DAYS it is also flagged `overdue`); an income is expected only
until its date + LATE_AFTER_DAYS, then it is late and no longer counted.

Cost (sec, #108): transactions are loaded and decrypted back to the oldest
active one-off item's date, up to SCAN_LIMIT_DAYS. One old item kept in the
app therefore makes every summary/forecast request decrypt up to a year of
transactions. Fine at today's sizes; if it shows up, cache matches per
request or cap the scan by item age.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, PlannedItem, PlannedKind, Transaction

from app.services.claude_keep import held_match_rules
from app.services.linked_commitments import linked_commitment_ids

from .commitments import CommitmentMatcher, build_commitment_matcher, current_commitment_matcher
from .common import _d, _load, resolve_roles

MATCH_DAYS = 7
# Income gets more grace (7 days) than an expense (3, OVERDUE_AFTER_DAYS):
# a late income only stops being counted, so a short wait costs nothing, and
# payers (refunds, invoices) often pay a few days late; an expense keeps
# counting either way, so its flag only needs to cover bank posting lag.
LATE_AFTER_DAYS = 7
# Income this far past its date is no longer listed as late (it's history).
INCOME_LOOKBACK_DAYS = 60
# An unpaid expense this far past its date is flagged "overdue, not seen
# paid": the same grace as late income, for bank posting lag (lead,
# 2026-10-11). Display only: it keeps counting either way.
OVERDUE_AFTER_DAYS = 3
# Transactions are scanned back to the oldest item's date, but no further
# than this. An expense older than that can't be seen paid, so it stays due
# (the safe side) until the user removes it.
SCAN_LIMIT_DAYS = 366
# Words that say nothing about who was paid.
_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "from", "to", "of", "a", "an", "my", "our", "your",
    "ltd", "limited", "plc", "llp", "inc", "co", "uk", "gb", "com", "www",
    "payment", "pay", "paid", "bill", "dd", "so", "direct", "debit", "standing", "order",
    "ref", "card", "transfer", "fp", "bp", "bgc",
})
_MIN_WORD = 3
TOLERANCE_FLOOR = Decimal("1.00")
TOLERANCE_SHARE = Decimal("0.02")


@dataclass(frozen=True)
class PlannedState:
    matched_transaction_id: uuid.UUID | None
    late: bool  # income only: unsettled past its date + LATE_AFTER_DAYS
    counted: bool  # whether it still counts as money in or out
    overdue: bool = False  # expense only: unsettled past its date + OVERDUE_AFTER_DAYS


def tolerance(amount: Decimal) -> Decimal:
    return max(TOLERANCE_FLOOR, (amount * TOLERANCE_SHARE).quantize(Decimal("0.01")))


def planned_states(db: Session, user, items: list[PlannedItem], today: date) -> dict[uuid.UUID, PlannedState]:
    """{one-off item id: state}, with Claude's unkept bill changes held.
    Recurring and plan items aren't matched."""
    one_offs = [i for i in items if i.kind == PlannedKind.ONE_OFF.value]
    if not one_offs:
        return {}
    current = current_commitment_matcher(db, user)
    held = build_commitment_matcher(held_match_rules(db, user.id), linked_commitment_ids(db, user.id))
    return _states(one_offs, _match(one_offs, _candidates(db, user, one_offs, today), (current, held)), today)


def _states(one_offs: list[PlannedItem], matches: dict, today: date) -> dict[uuid.UUID, PlannedState]:
    states = {}
    for item in one_offs:
        matched = matches.get(item.id)
        if item.direction == "income":
            past_due = today > item.start_date + timedelta(days=LATE_AFTER_DAYS)
            history = item.start_date < today - timedelta(days=INCOME_LOOKBACK_DAYS)
            late = matched is None and past_due and not history
            states[item.id] = PlannedState(matched, late, matched is None and not past_due)
        else:
            overdue = matched is None and today > item.start_date + timedelta(days=OVERDUE_AFTER_DAYS)
            states[item.id] = PlannedState(matched, False, matched is None, overdue)
    return states


def _candidates(db: Session, user, items: list[PlannedItem], today: date) -> list[Transaction]:
    """Real-money transactions in the items' scan window, before the
    commitment exclusion (which depends on the view)."""
    oldest = max(min(i.start_date for i in items), today - timedelta(days=SCAN_LIMIT_DAYS))
    start = oldest - timedelta(days=MATCH_DAYS + 2)  # +2: transfer pairing
    txns = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.transaction_date >= datetime.combine(start, time.min, timezone.utc),
        )
        .all()
    )
    return _real_money(db, user, txns)


def _match(items: list[PlannedItem], candidates: list[Transaction],
           commitments: tuple[CommitmentMatcher, ...]) -> dict[uuid.UUID, uuid.UUID]:
    """{item id: transaction id}, leaving out any payment one of the
    `commitments` matchers takes for a commitment's."""
    eligible = [tx for tx in candidates if not any(m.matches(tx) for m in commitments)]
    used: set = set()
    out: dict = {}
    for item in sorted(items, key=lambda i: (i.start_date, str(i.id))):
        want = "credit" if item.direction == "income" else "debit"
        amount = _d(item.amount)
        item_words = _words(item.name)
        best = None
        for tx in eligible:
            if tx.id in used or tx.transaction_type != want:
                continue
            gap = abs((tx.transaction_date.date() - item.start_date).days)
            diff = abs(_d(tx.amount) - amount)
            if gap > MATCH_DAYS or diff > tolerance(amount):
                continue
            if diff and not item_words & _words(f"{tx.merchant_name or ''} {tx.description or ''}"):
                continue  # near the amount but nothing ties it to this item
            key = (gap, abs(_d(tx.amount) - amount), str(tx.id))
            if best is None or key < best[0]:
                best = (key, tx)
        if best is not None:
            used.add(best[1].id)
            out[item.id] = best[1].id
    return out


def _words(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", text.casefold())
        if len(w) >= _MIN_WORD and w not in _STOP_WORDS
    }


def _real_money(db: Session, user, txns: list[Transaction]) -> list[Transaction]:
    """Transactions that can settle a planned item: the same exclusions the
    spending figures use, so moving money between your own accounts or paying
    a card never 'pays' a planned bill. Commitment payments are left out
    later, by `_match`."""
    from .spending import classify_noise, financed_transaction_ids

    accounts, settings = _load(db, user)
    noise = classify_noise(txns, resolve_roles(accounts, settings))
    financed = financed_transaction_ids(db, user)
    return [tx for tx in txns if tx.id not in noise and tx.id not in financed]
