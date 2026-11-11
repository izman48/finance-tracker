"""What stops or questions a new paid-back mark (T-03-3 P4; PRD decision 3).

A marked credit never counts as income: detection, planned-income settling
and late-income clearing all skip it. So marking a credit that is income
today would quietly turn that income into a miss. Two checks guard that,
both computed per request with the user's key:

- **blocked**: the credit settles a planned income item, or pays a confirmed
  income's latest payment (late or still inside its grace days). The user
  changes that in the app first.
- **warned**: the credit's payer has a suggested or confirmed income
  commitment. Claude asks the user before marking it.

There is no loop: a marked credit is skipped by all three, so it can't
become "locked" later, and an unmarked one is checked when it is marked.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date

from sqlalchemy.orm import Session

from app.models import (
    Account,
    CommitmentDirection,
    CommitmentRule,
    CommitmentStatus,
    PlannedItem,
    PlannedKind,
    Transaction,
)
from app.services.analytics.late_income import income_credit_ids, income_rule_keys, payer_words
from app.services.analytics.planned_matching import planned_states

PLANNED_INCOME, LATE_INCOME = "planned_income", "late_income"


def income_locked_credit_ids(db: Session, user, today: date) -> dict[uuid.UUID, str]:
    """{credit id: why it can't be marked}: `planned_income` or `late_income`."""
    locked = dict.fromkeys(income_credit_ids(db, user, today), LATE_INCOME)
    items = (
        db.query(PlannedItem)
        .filter(
            PlannedItem.user_id == user.id, PlannedItem.direction == "income",
            PlannedItem.kind == PlannedKind.ONE_OFF.value, PlannedItem.active.is_(True),
            PlannedItem.deleted_at.is_(None),
        )
        .all()
    )
    if items:
        for state in planned_states(db, user, items, today).values():
            if state.matched_transaction_id is not None:
                locked[state.matched_transaction_id] = PLANNED_INCOME
    return locked


def income_commitment_payers(db: Session, user, credit_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Those of the user's credits whose payer has a suggested or confirmed
    income commitment: likely income, so a mark needs the user's say-so.
    Other users' ids are never read."""
    ids = set(credit_ids)
    if not ids:
        return set()
    rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status.in_([CommitmentStatus.SUGGESTED.value, CommitmentStatus.CONFIRMED.value]),
        )
        .all()
    )
    payers = {payer_words(key.split(":", 1)[1]) for rule in rules for key in income_rule_keys(rule)} - {()}
    if not payers:
        return set()
    credits = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user.id, Transaction.id.in_(ids), Transaction.transaction_type == "credit")
        .all()
    )
    return {tx.id for tx in credits if payer_words(tx.merchant_name or tx.description or "") in payers}
