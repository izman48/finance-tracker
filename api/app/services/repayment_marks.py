"""Reading repayment marks (T-03-3 P1; T-03-2 decision T10).

Marks are read per request with the user's key: their amounts are
encrypted, so no SQL sums them and no background job can. Every read clamps
the active marks, oldest first, so that a credit is never marked past its
own amount and a spend never netted past its own, whatever the rows say
(writes check the same caps, under `lock_user_marks`; the clamp is the
backstop). Only the user's own transactions count: a mark naming any other
transaction applies nothing.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, RepaymentMark, Transaction, User


@dataclass(frozen=True)
class AppliedMark:
    id: uuid.UUID | None  # None: a proposed mark (`extra`), not saved
    credit_id: uuid.UUID
    spend_id: uuid.UUID | None  # None: a category mark
    category: str | None
    recorded: Decimal  # the amount saved on the mark
    applied_amount: Decimal  # what it nets after the caps
    credit_at: datetime  # when the credit arrived: a category mark nets in that cycle
    created_at: datetime | None  # when it was marked; None for a proposed mark
    label: str
    created_via: str


def lock_user_marks(db: Session, user_id: uuid.UUID) -> None:
    """Serialise mark writes per user (the user row, FOR UPDATE), so two at
    once can't both pass a cap check. A no-op on SQLite (one writer)."""
    db.query(User.id).filter(User.id == user_id).with_for_update().one()


def active_marks(db: Session, user_id: uuid.UUID, extra: Sequence[RepaymentMark] = ()) -> list[AppliedMark]:
    """The user's active marks, oldest first, each with its clamped amount.

    `extra`: unsaved marks a preview proposes (T-03-2 T7), netted after the
    saved ones as the newest, in the order given. They are never added to
    the session."""
    marks = _active_rows(db, user_id) + list(extra)
    txns = _own_transactions(db, user_id, _referenced_ids(marks))
    left = {tx_id: _amount(tx) for tx_id, tx in txns.items()}
    applied = []
    for mark in marks:
        amount = _clamp(mark, left)
        credit = txns.get(mark.credit_transaction_id)
        if credit is None:  # not the user's: it could never apply
            continue
        applied.append(AppliedMark(
            id=mark.id, credit_id=mark.credit_transaction_id, spend_id=mark.spend_transaction_id,
            category=mark.category, recorded=Decimal(mark.amount), applied_amount=amount,
            credit_at=credit.transaction_date, created_at=mark.created_at, label=mark.label,
            created_via=mark.created_via,
        ))
    return applied


def remaining(db: Session, user_id: uuid.UUID, transaction_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """{transaction id: amount not yet marked} for those of the ids that are
    the user's own: a credit less its applied marks, a spend less the marks
    against it. Unknown and other users' ids are left out (callers 404)."""
    marks = _active_rows(db, user_id)
    wanted = set(transaction_ids)
    txns = _own_transactions(db, user_id, wanted | _referenced_ids(marks))
    left = {tx_id: _amount(tx) for tx_id, tx in txns.items()}
    for mark in marks:
        _clamp(mark, left)
    return {tx_id: left[tx_id] for tx_id in wanted if tx_id in left}


def fits(db: Session, user_id: uuid.UUID, credit_id: uuid.UUID, spend_id: uuid.UUID | None,
         amount: Decimal) -> bool:
    """Whether a mark of `amount` on this credit (and spend) stays within
    what is left on both. Call under `lock_user_marks`."""
    ids = [credit_id] if spend_id is None else [credit_id, spend_id]
    left = remaining(db, user_id, ids)
    return all(i in left and amount <= left[i] for i in ids)


def _active_rows(db: Session, user_id: uuid.UUID) -> list[RepaymentMark]:
    return (
        db.query(RepaymentMark)
        .filter(RepaymentMark.user_id == user_id, RepaymentMark.active.is_(True))
        .order_by(RepaymentMark.created_at, RepaymentMark.id)
        .all()
    )


def _referenced_ids(marks: list[RepaymentMark]) -> set[uuid.UUID]:
    ids = {m.credit_transaction_id for m in marks}
    return ids | {m.spend_transaction_id for m in marks if m.spend_transaction_id is not None}


def _own_transactions(db: Session, user_id: uuid.UUID, ids: set[uuid.UUID]) -> dict[uuid.UUID, Transaction]:
    if not ids:
        return {}
    rows = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user_id, Transaction.id.in_(ids))
        .all()
    )
    return {tx.id: tx for tx in rows}


def _amount(tx: Transaction) -> Decimal:
    return abs(Decimal(str(tx.amount or 0)))


def _clamp(mark: RepaymentMark, left: dict[uuid.UUID, Decimal]) -> Decimal:
    """What this mark can still apply, taken off what is left on its credit
    and spend. A transaction that isn't the user's has nothing left."""
    targets = [mark.credit_transaction_id]
    if mark.spend_transaction_id is not None:
        targets.append(mark.spend_transaction_id)
    amount = max(Decimal(0), min([Decimal(mark.amount)] + [left.get(t, Decimal(0)) for t in targets]))
    for t in targets:
        if t in left:
            left[t] -= amount
    return amount
