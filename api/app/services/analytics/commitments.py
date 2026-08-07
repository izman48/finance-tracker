"""Recurring commitments: detection, match keys, paydays, and transaction conversion."""
from __future__ import annotations

import re
import statistics
import uuid as _uuid
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Account,
    AccountRole,
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
from .common import _d, _load, _today, detect_internal_transfers, is_card_settlement, resolve_roles

# Detection thresholds (mirrors the frontend Bills heuristic).
_MIN_OCCURRENCES = 3
_MAX_INTERVAL_CV = 0.30  # std-dev must be < 30% of the mean interval

# Tokens that vary between otherwise-identical payments, so they must not be
# part of the grouping key. Banks rarely populate merchant_name for direct
# debits and standing orders, so we fall back to the description — which often
# carries a per-payment reference ("LOAN PAYMENT REF 4471"). Left in, every
# month lands in its own group of one and never reaches _MIN_OCCURRENCES, so a
# perfectly regular loan or bill is invisible to detection.
_DIGIT_RUN = re.compile(r"^\d{3,}$")                       # 4471, 0123456
_DATE_TOKEN = re.compile(r"^\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?$")  # 12/07, 12-07-25
# A long digit run *inside* an otherwise alphanumeric token is a mandate or
# account reference, not part of the name: "Q42181371737681503" (EE),
# "UUID-12331371342" (Ikano), "A1539913" (CommunityFibre). Six is the
# threshold that keeps real names whose digits are short — "O2", "MONZO123",
# "1606LANDMARKE" — while catching every reference format we've seen.
_REFERENCE_RUN = re.compile(r"\d{6,}")


def _normalise_merchant(raw: str | None) -> str:
    """Collapse a bank description to a key that's stable across payments.

    Conservative: pure digit runs, dates, and alphanumeric tokens carrying a
    long digit run are dropped. Short mixed alphanumerics are left alone,
    because stripping those would eat real merchant names ("O2", "MONZO123")
    and over-merge unrelated payments.
    """
    text = re.sub(r"[^A-Z0-9/\- ]+", " ", (raw or "").upper())
    tokens = [
        t for t in text.split()
        if not _DIGIT_RUN.match(t)
        and not _DATE_TOKEN.match(t)
        and not _REFERENCE_RUN.search(t)
    ]
    # Fall back to the raw text if normalising left nothing (e.g. "123456").
    return " ".join(tokens).strip() or (raw or "").strip().upper()


def _match_key(direction: str, merchant: str) -> str:
    # Normalised, so the same real-world payment keys identically however its
    # reference varies. For merchants without digits this is byte-identical to
    # the old `merchant.strip().lower()`, so existing stored keys still match.
    return f"{direction}:{_normalise_merchant(merchant).lower()}"


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

    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    transfers = detect_internal_transfers(txns)

    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for tx in txns:
        role = roles.get(tx.account_id)
        # Accounts held out of the cashflow picture shouldn't generate
        # commitments — including the loan/mortgage accounts that default to
        # excluded, whose incoming payments would otherwise read as income.
        if role == AccountRole.EXCLUDED:
            continue
        # Card settlements are already modelled as repayment events, derived
        # from the card's balance and schedule; detecting them here as well
        # would count the same money twice in safe-to-spend and the forecast.
        if is_card_settlement(tx, role):
            continue
        # Only the *receiving* leg of a transfer between your own accounts is
        # dropped — that isn't income. The paying leg is kept deliberately: a
        # standing order into savings is still a real monthly outflow, and the
        # forecast overstates your balance if it doesn't know about it.
        if tx.transaction_type == "credit" and tx.id in transfers:
            continue
        direction = (
            CommitmentDirection.INCOME.value
            if tx.transaction_type == "credit"
            else CommitmentDirection.EXPENSE.value
        )
        raw = (tx.merchant_name or tx.description or "Unknown").strip()
        groups[(direction, _normalise_merchant(raw))].append(tx)

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

        # Label from the real descriptions, not the normalised key — the key is
        # an internal grouping artefact and reads badly ("LOAN PAYMENT REF").
        display = Counter(
            (t.merchant_name or t.description or "Unknown").strip() for t in group
        ).most_common(1)[0][0]

        candidates.append(
            {
                "direction": direction,
                "label": display,
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

    # Re-key detected rules whose match_key predates a change in how merchants
    # are normalised. match_key is DEK-encrypted, so this can't be a SQL data
    # migration — it heals here, where the user's key is in scope. Without it a
    # stale key stops matching its transactions (they'd leak back into spending)
    # and stops suppressing re-detection (the same commitment gets suggested
    # again as a duplicate). Only DETECTED rules: their key has always been
    # derived from the label, whereas a manual rule's key is the user's own
    # merchant text and is not ours to rewrite.
    for rule in existing_rules:
        if rule.source != CommitmentSource.DETECTED.value or not rule.match_key:
            continue
        expected = _match_key(rule.direction, rule.label or "")
        if rule.match_key != expected:
            rule.match_key = expected

    # Dedupe on the stored key *and* the key the label derives today. A manual
    # rule's stored key is the user's own text and is deliberately never
    # rewritten above, so after a normalisation change it can go stale — and a
    # stale key suppresses nothing, letting detection re-add the very
    # commitment the user already has. Deriving from the label as well closes
    # that without touching what the user typed.
    existing_keys = {rule.match_key for rule in existing_rules if rule.match_key}
    existing_keys |= {
        _match_key(rule.direction, rule.label) for rule in existing_rules if rule.label
    }

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


def _payday_incomes(db: Session, user) -> list[CommitmentRule]:
    """Confirmed income rules that define payday.

    With several income streams the nearest credit (a freelance invoice, bank
    interest) isn't payday. If the user has flagged which income is their payday
    (is_payday), only those count; otherwise every confirmed income does, as
    before. This is what safe-to-spend, the forecast and the since-payday window
    all key off.
    """
    incomes = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    flagged = [r for r in incomes if r.is_payday]
    return flagged or incomes


def next_payday(db: Session, user, from_date: date) -> date | None:
    """Next payday income date on/after from_date."""
    incomes = _payday_incomes(db, user)
    dates = [occ for r in incomes for occ in commitment_occurrences(r, from_date, from_date + timedelta(days=400))]
    return min(dates) if dates else None


def last_payday(db: Session, user, today: date) -> date | None:
    """Most recent payday income date on/before today (steps back from next_date)."""
    incomes = _payday_incomes(db, user)
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
