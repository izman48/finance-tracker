"""Paid-back marks as the transaction list and search show them (T-03-3 P6;
T-03-2 section 5).

`paid_back_view` gives, for a page of transactions, each one's marks (as a
credit or as a spend) and, for debits, what they net. A mark applies only
while its spend still counts as spending (AC-29: a spend set to a transfer
nets nothing, and the app says "Not applied"). A mark's cycle is closed when
the day it nets on (the spend's, or the credit's for a category mark) is
before the current budget cycle (decision 6). Read with the user's key, per
request; only the user's own marks and transactions.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, Transaction
from app.services.analytics.commitments import commitment_match_keys
from app.services.analytics.common import _load, _today, resolve_roles
from app.services.analytics.spending import _effective_transfers, classify_purchase, financed_transaction_ids
from app.services.budgets import current_cycle
from app.services.planning_writes import claude_markers
from app.services.repayment_marks import active_marks

# Transfer pairs are found among nearby transactions.
_PAIRING_DAYS = 7


@dataclass
class PaidBackView:
    marks: dict[uuid.UUID, list[dict]] = field(default_factory=dict)  # transaction id -> its marks
    netted: dict[uuid.UUID, Decimal] = field(default_factory=dict)    # spend id -> what applies


def paid_back_view(db: Session, user, txns: list[Transaction]) -> PaidBackView:
    page = {tx.id for tx in txns}
    marks = [m for m in active_marks(db, user.id) if m.credit_id in page or m.spend_id in page]
    if not marks:
        return PaidBackView()
    spend_ids = {m.spend_id for m in marks if m.spend_id is not None}
    spends = _own(db, user, spend_ids)
    credits = _own(db, user, {m.credit_id for m in marks})
    counted = _still_counted(db, user, list(spends.values()))
    audits = claude_markers(db, user.id, "repayment_mark", [m.id for m in marks])
    cycle_start = current_cycle(db, user, _today()).start

    view = PaidBackView()
    for m in marks:
        applies = m.applied_amount > 0 and (m.spend_id is None or m.spend_id in counted)
        spend, credit = spends.get(m.spend_id), credits.get(m.credit_id)
        day = spend.transaction_date if spend is not None else m.credit_at
        row = {
            "mark_id": str(m.id), "credit_id": str(m.credit_id),
            "spend_id": str(m.spend_id) if m.spend_id else None, "category": m.category,
            "amount": f"{m.applied_amount:.2f}", "label": m.label, "created_via": m.created_via,
            "applied": applies, "cycle_closed": _utc_day(day) < cycle_start,
            "audit_id": str(audits[m.id]["audit_id"]) if m.id in audits else None,
            # For the sheet's rows (PRD Screens 1): who paid, what it paid back, and when.
            "payer": _name(credit), "against": _name(spend) if spend is not None else m.category,
            "credit_date": _utc_day(m.credit_at), "spend_date": _utc_day(spend.transaction_date) if spend else None,
        }
        for tx_id in (m.credit_id, m.spend_id):
            if tx_id in page:
                view.marks.setdefault(tx_id, []).append(row)
        if applies and m.spend_id is not None:
            view.netted[m.spend_id] = view.netted.get(m.spend_id, Decimal(0)) + m.applied_amount
    return view


def _still_counted(db: Session, user, spends: list[Transaction]) -> set[uuid.UUID]:
    """Those spends that the purchases lens still counts (card or cash)."""
    if not spends:
        return set()
    days = [_utc_day(s.transaction_date) for s in spends]
    start = datetime.combine(min(days) - timedelta(days=_PAIRING_DAYS), time.min, timezone.utc)
    end = datetime.combine(max(days) + timedelta(days=_PAIRING_DAYS), time.max, timezone.utc)
    nearby = (
        db.query(Transaction).join(Account)
        .filter(Account.user_id == user.id, Transaction.transaction_date >= start,
                Transaction.transaction_date <= end)
        .all()
    )
    accounts, settings = _load(db, user)
    roles, transfers = resolve_roles(accounts, settings), _effective_transfers(nearby)
    financed, keys = financed_transaction_ids(db, user), commitment_match_keys(db, user)
    return {s.id for s in spends if classify_purchase(s, transfers, roles, financed, keys) in ("credit", "cash")}


def _name(tx: Transaction | None) -> str | None:
    return None if tx is None else (tx.merchant_name or tx.description)


def _own(db: Session, user, ids: set[uuid.UUID]) -> dict[uuid.UUID, Transaction]:
    if not ids:
        return {}
    rows = db.query(Transaction).join(Account).filter(Account.user_id == user.id, Transaction.id.in_(ids)).all()
    return {tx.id: tx for tx in rows}


def _utc_day(moment: datetime) -> date:
    # Budget cycles are UTC days, as the transaction windows that build them.
    return (moment.astimezone(timezone.utc) if moment.tzinfo else moment).date()
