"""Checking Claude's paid-back marks before any is saved (T-03-3 P5b; PRD
"MCP contract" error table; T-03-2 decisions T10, T11).

`plan_marks` runs every check for a whole call and returns what to save, or
raises with the PRD's sentence: 404 "Not found" for a payment that isn't
the user's (never whose), 422 for everything else. The caller holds
`lock_user_marks`, so the caps can't be raced. Amounts, merchant names and
descriptions are encrypted, so all of this runs in Python with the user's key.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.display_text import has_hidden_characters
from app.models import Account, RepaymentMark, Transaction
from app.schemas.repayments import MarkEntry
from app.services.analytics.commitments import commitment_match_keys
from app.services.analytics.common import _load, _today, resolve_roles
from app.services.analytics.spending import _effective_transfers, classify_purchase, financed_transaction_ids
from app.services.repayment_guards import income_commitment_payers, income_locked_credit_ids
from app.services.repayment_marks import remaining

WARN_INCOME_PAYER = "income_commitment_payer"
# Transfer pairs are found among nearby transactions (detection pairs legs a few days apart).
_PAIRING_DAYS = 7
_LABEL_PART = 40


@dataclass
class PlannedMark:
    entry: MarkEntry
    amount: Decimal
    label: str
    existing: RepaymentMark | None = None  # the identical active mark: unchanged
    warnings: list[str] = field(default_factory=list)


def plan_marks(db: Session, user, entries: list[MarkEntry], *, accept_warnings: bool,
               dry_run: bool) -> list[PlannedMark]:
    for e in entries:
        if e.spend_id is None and e.category is None:
            raise _refuse("Pass spend_id, or a category to net against.")
        if e.spend_id is not None and e.category is not None:
            raise _refuse("Pass spend_id or category, not both.")
    if len({(e.credit_id, e.spend_id, e.category) for e in entries}) != len(entries):
        raise _refuse("Pass each payment and target once.")

    ids = {e.credit_id for e in entries} | {e.spend_id for e in entries if e.spend_id}
    txns = _own(db, user, ids)
    if ids - set(txns):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    categories = _user_categories(db, user)
    locked = income_locked_credit_ids(db, user, _today())
    warned = income_commitment_payers(db, user, [e.credit_id for e in entries])
    left = remaining(db, user.id, ids)
    marks = _active_marks_by_target(db, user, {e.credit_id for e in entries})

    plans = []
    for e in entries:
        credit = txns[e.credit_id]
        if credit.transaction_type != "credit":
            raise _refuse("credit_id must be an incoming payment.")
        spend = txns.get(e.spend_id) if e.spend_id else None
        if spend is not None:
            _check_spend(db, user, spend)
        elif e.category not in categories or has_hidden_characters(e.category):
            raise _refuse("That is not one of the user's categories.")
        if credit.id in locked:
            raise _refuse("This payment is already counted as income. The user must change that in the app first.")
        warnings = [WARN_INCOME_PAYER] if credit.id in warned else []
        if warnings and not accept_warnings and not dry_run:
            raise _refuse("The payer looks like regular income. Ask the user, then retry with accept_warnings=true.")

        existing = marks.get((e.credit_id, e.spend_id, e.category))
        if existing is not None:
            if e.amount_pounds is not None and e.amount_pounds != Decimal(existing.amount):
                raise _refuse(f"Already marked £{Decimal(existing.amount):.2f}. Unmark it first to change the amount.")
            plans.append(PlannedMark(e, Decimal(existing.amount), existing.label, existing, warnings))
            continue
        amount = _within_caps(e, left[credit.id], left[spend.id] if spend is not None else None)
        left[credit.id] -= amount
        if spend is not None:
            left[spend.id] -= amount
        plans.append(PlannedMark(e, amount, _label(credit, amount, spend, e.category), None, warnings))
    return plans


def _within_caps(e: MarkEntry, credit_left: Decimal, spend_left: Decimal | None) -> Decimal:
    """The amount to mark: as asked, or the smaller room (PRD: amount_pounds
    defaults to the smaller of the credit's unmarked amount and the spend's
    remaining). Over either cap, or nothing left, is refused."""
    room = credit_left if spend_left is None else min(credit_left, spend_left)
    amount = e.amount_pounds if e.amount_pounds is not None else room
    if amount > credit_left or credit_left <= 0:
        raise _refuse(f"That is more than this payment. Up to £{max(credit_left, Decimal(0)):.2f} is unmarked.")
    if spend_left is not None and (amount > spend_left or spend_left <= 0):
        raise _refuse(f"That is more than this spend. You can mark up to £{max(spend_left, Decimal(0)):.2f}.")
    return amount


def _check_spend(db: Session, user, spend: Transaction) -> None:
    """The spend must be a purchase that budgets count (PRD decisions 5, 10)."""
    if spend.transaction_type != "debit":
        raise _refuse("spend_id must be a purchase.")
    accounts, settings = _load(db, user)
    nearby = _own_between(db, user, spend.transaction_date - timedelta(days=_PAIRING_DAYS),
                          spend.transaction_date + timedelta(days=_PAIRING_DAYS))
    kind = classify_purchase(spend, _effective_transfers(nearby), resolve_roles(accounts, settings),
                             financed_transaction_ids(db, user), commitment_match_keys(db, user))
    if kind == "commitment":
        raise _refuse("That purchase is a commitment, which budgets never count. Mark a category instead, or leave it.")
    if kind not in ("credit", "cash"):
        raise _refuse("That purchase is not counted as spending (financed, transfer or card payoff). "
                      "The user must set it to count as spending in the app first.")


def _own(db: Session, user, ids: set[uuid.UUID]) -> dict[uuid.UUID, Transaction]:
    rows = db.query(Transaction).join(Account).filter(Account.user_id == user.id, Transaction.id.in_(ids)).all()
    return {tx.id: tx for tx in rows}


def _own_between(db: Session, user, start: datetime, end: datetime) -> list[Transaction]:
    return (
        db.query(Transaction).join(Account)
        .filter(Account.user_id == user.id, Transaction.transaction_date >= start,
                Transaction.transaction_date <= end)
        .all()
    )


def _user_categories(db: Session, user) -> set[str]:
    rows = (
        db.query(Transaction.category).join(Account)
        .filter(Account.user_id == user.id, Transaction.category.is_not(None))
        .distinct().all()
    )
    return {category for (category,) in rows}


def _active_marks_by_target(db: Session, user, credit_ids: set[uuid.UUID]) -> dict[tuple, RepaymentMark]:
    rows = (
        db.query(RepaymentMark)
        .filter(RepaymentMark.user_id == user.id, RepaymentMark.active.is_(True),
                RepaymentMark.credit_transaction_id.in_(credit_ids))
        .all()
    )
    return {(m.credit_transaction_id, m.spend_transaction_id, m.category): m for m in rows}


def _label(credit: Transaction, amount: Decimal, spend: Transaction | None, category: str | None) -> str:
    """"Sam £60.00, Pizza Express": bank text, shown as data only."""
    payer = (credit.merchant_name or credit.description or "Payment").strip()[:_LABEL_PART]
    against = (spend.merchant_name or spend.description or "Purchase").strip() if spend is not None else category
    return f"{payer} £{amount:.2f}, {against[:_LABEL_PART]}"


def _refuse(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
