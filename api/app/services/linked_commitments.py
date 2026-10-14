"""Guard for commitments that carry a liability's repayment (T-10-8b).

The liability is the source of truth (sec T-10-8): the user's web edits and
skip, mark-as-recurring, Claude's update and dismiss tools, and undoing an
earlier Claude change all get 409 for the repayment's amount, cadence, dates
and status. Renaming the bill stays open. Models only, so any service can
import it without a cycle.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Liability

GUARDED_FIELDS = frozenset({"amount", "cadence", "interval_days", "interval_months", "next_date", "status"})
LINKED_DETAIL = {
    "code": "linked_to_liability",
    "message": "This payment follows your loan. Change it on Wealth, under Loans and finance.",
}


class LinkedCommitmentEdit(Exception):
    """A write would change a guarded field of a linked commitment."""


def linked_commitment_ids(db: Session, user_id: uuid.UUID) -> set:
    rows = db.query(Liability.linked_commitment_id).filter(
        Liability.user_id == user_id, Liability.linked_commitment_id.isnot(None),
    )
    return {row[0] for row in rows}


def check(db: Session, user_id: uuid.UUID, commitment_id: uuid.UUID, fields) -> None:
    """Raise LinkedCommitmentEdit if `fields` touch a guarded field of a
    commitment linked to one of this user's liabilities."""
    if GUARDED_FIELDS & set(fields) and commitment_id in linked_commitment_ids(db, user_id):
        raise LinkedCommitmentEdit()


def refuse_linked_edit(db: Session, user_id: uuid.UUID, commitment_id: uuid.UUID, fields) -> None:
    """`check` for routes: 409 with the "edit the loan" detail."""
    try:
        check(db, user_id, commitment_id, fields)
    except LinkedCommitmentEdit:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=LINKED_DETAIL) from None
