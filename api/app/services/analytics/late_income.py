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

It clears when the money came (T-08-23): one credit whose merchant key
matches the commitment (its match_key, or its label's key) within
max(GBP 1, 2%) of the expected amount, or credits from the same payer
within a week either side of the expected date that together come to at
least the expected amount less that tolerance. A payer often splits one
payment ("PAYER X RENT" + "PAYER X MAMA AND DADA") or varies it; a stray
GBP 5 from the payer still doesn't hide a missing GBP 1,000. The payer is
the leading words of the description, before the free-text reference
(`_payer`). Credits the user marked as a transfer count here, for this
check only (it changes no figure); detected internal transfer legs and
card payments never do: money moved in from your own savings isn't the
income. Skip on a late income settles that payment (`skipped_through`).
Recomputed on every read, with the user's key.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, CommitmentDirection, CommitmentRule, CommitmentStatus, Transaction

from .cadence import _step, _step_back
from .commitments import _match_key, _normalise_merchant, transaction_match_key
from .common import _d, _load, detect_internal_transfers, resolve_roles
from .planned_matching import _STOP_WORDS, tolerance

GRACE_DAYS = 3
EARLY_DAYS = 7  # a payment this many days early still counts
SPLIT_DAYS = 7  # credits from the payer this close to the expected date add up
PAYER_WORDS = 2  # the leading words of a description that name the payer
# Leading words a bank puts before the payer's name (sec on #133).
_BANK_PREFIX = _STOP_WORDS | {
    "faster", "payments", "bank", "giro", "credit", "fps", "bacs", "chaps", "tfr", "received", "receipt",
}


@dataclass(frozen=True)
class _Credit:
    key: str
    payer: tuple[str, ...]
    day: date
    amount: Decimal


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
        skipped = rule.skipped_through is not None and expected <= rule.skipped_through
        if today - expected > timedelta(days=GRACE_DAYS) and created <= expected and not skipped:
            candidates.append((rule, expected))
    if not candidates:
        return {}
    credits = _income_credits(db, user, min(e for _, e in candidates) - timedelta(days=EARLY_DAYS))
    # Each credit pays one income (eng-a on #133): exact matches first, then
    # the payer's leftover credits, soonest expected income first.
    unused = list(credits)
    waiting = []
    for rule, expected in sorted(candidates, key=lambda c: c[1]):
        match = _exact_match(rule, expected, unused)
        if match is None:
            waiting.append((rule, expected))
        else:
            unused.remove(match)
    out = {}
    for rule, expected in waiting:
        used = _split_match(rule, expected, unused)
        if used is None:
            out[rule.id] = LateIncome(rule.id, rule.label, _d(rule.amount), expected)
        else:
            for c in used:
                unused.remove(c)
    return out


def _keys(rule: CommitmentRule) -> set[str]:
    return {k for k in (rule.match_key, _match_key(rule.direction, rule.label)) if k}


def _exact_match(rule: CommitmentRule, expected: date, credits: list[_Credit]) -> _Credit | None:
    """One credit with the commitment's own key, within tolerance."""
    keys, amount = _keys(rule), _d(rule.amount)
    allowed = tolerance(amount)  # the same rule as planned items (T-08-7)
    early = expected - timedelta(days=EARLY_DAYS)
    return next(
        (c for c in credits if c.key in keys and c.day >= early and abs(c.amount - amount) <= allowed),
        None,
    )


def _split_match(rule: CommitmentRule, expected: date, credits: list[_Credit]) -> list[_Credit] | None:
    """Credits from the same payer near the expected date that together make
    at least the expected amount less tolerance, taken in date order until
    they do; None if they don't."""
    payers = {_payer(k.split(":", 1)[1]) for k in _keys(rule)} - {()}
    amount = _d(rule.amount)
    needed = amount - tolerance(amount)
    near = sorted(
        (c for c in credits if c.payer in payers and abs((c.day - expected).days) <= SPLIT_DAYS),
        key=lambda c: c.day,
    )
    used, total = [], Decimal(0)
    for c in near:
        used.append(c)
        total += c.amount
        if total >= needed:
            return used
    return None


def _payer(text: str) -> tuple[str, ...]:
    """The payer's name: the leading words of a normalised description after
    any bank prefix ("FASTER PAYMENT", "BANK GIRO CREDIT", "TRANSFER FROM")
    and before the free-text reference ("PAYER X RENT" -> payer x)."""
    words = _normalise_merchant(text).lower().split()
    while words and words[0] in _BANK_PREFIX:
        words.pop(0)
    return tuple(words[:PAYER_WORDS])


def _income_credits(db: Session, user, since: date) -> list[_Credit]:
    """Credits since `since` that could be the income: not a detected
    internal transfer leg (money from your own accounts) and not a card
    payment. One the user marked as a transfer (override or transfer
    category) still counts here: it is often pass-through money that did
    arrive, and this check moves no figure. Spending and safe-to-spend keep
    excluding it."""
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
    own_legs = detect_internal_transfers(txns)
    marked = {
        tx.id for tx in txns
        if tx.id in noise and noise[tx.id] == "internal_transfer" and tx.id not in own_legs
    }
    return [
        _Credit(
            transaction_match_key(tx), _payer(tx.merchant_name or tx.description or ""),
            tx.transaction_date.date(), _d(tx.amount),
        )
        for tx in txns
        if tx.transaction_type == "credit"
        and (tx.id not in noise or tx.id in marked)
        and tx.transaction_date.date() >= since
    ]
