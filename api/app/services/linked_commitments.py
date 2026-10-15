"""Guard for commitments that carry a holding's repayment or contribution
(T-10-8b; generalised in T-11-3b, ADR-002 section 3).

The holding is the source of truth (sec T-10-8): the user's web edits and
skip, mark-as-recurring, Claude's update and dismiss tools, and undoing an
earlier Claude change all get 409 for the bill's amount, cadence, dates and
status. Renaming the bill stays open. The link set is the union of loan links
(`liabilities.linked_commitment_id`) and `commitment_links`, so every caller
of `linked_commitment_ids` covers both. Models only, so any service can
import it without a cycle.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import CommitmentLink, Liability

# `card_account_id` too (sec on #183): tying the bill to a card would let the
# card's larger repayment replace it in safe-to-spend and the forecast.
GUARDED_FIELDS = frozenset({
    "amount", "cadence", "interval_days", "interval_months", "next_date", "status", "card_account_id",
})
LINKED_DETAIL = {
    "code": "linked_to_liability",
    "message": "This payment follows your loan. Change it on Wealth, under Loans and finance.",
}
HOLDING_DETAIL = {
    "code": "linked_to_holding",
    "message": "This payment follows your investment. Change it on Wealth, under Investments.",
}


@dataclass(frozen=True)
class LinkOwner:
    kind: Literal["liability", "holding"]
    owner_id: uuid.UUID

    @property
    def detail(self) -> dict:
        return LINKED_DETAIL if self.kind == "liability" else HOLDING_DETAIL


class LinkedCommitmentEdit(Exception):
    """A write would change a guarded field of a linked commitment."""

    def __init__(self, owner: LinkOwner):
        self.owner = owner
        super().__init__(owner.kind)


def linked_commitments(db: Session, user_id: uuid.UUID) -> dict[uuid.UUID, LinkOwner]:
    """Every linked commitment of this user and what it belongs to. A loan
    link counts from either store, so a missing link row never drops a guard."""
    owners = {
        row.commitment_id: LinkOwner(
            "liability" if row.liability_id is not None else "holding", row.liability_id or row.asset_id,
        )
        for row in db.query(CommitmentLink).filter(CommitmentLink.user_id == user_id)
    }
    loans = db.query(Liability.id, Liability.linked_commitment_id).filter(
        Liability.user_id == user_id, Liability.linked_commitment_id.isnot(None),
    )
    for liability_id, commitment_id in loans:
        owners[commitment_id] = LinkOwner("liability", liability_id)
    return owners


def linked_commitment_ids(db: Session, user_id: uuid.UUID) -> set:
    return set(linked_commitments(db, user_id))


def check(db: Session, user_id: uuid.UUID, commitment_id: uuid.UUID, fields) -> None:
    """Raise LinkedCommitmentEdit if `fields` touch a guarded field of a
    commitment linked to one of this user's holdings."""
    if not GUARDED_FIELDS & set(fields):
        return
    owner = linked_commitments(db, user_id).get(commitment_id)
    if owner is not None:
        raise LinkedCommitmentEdit(owner)


def refuse_linked_edit(db: Session, user_id: uuid.UUID, commitment_id: uuid.UUID, fields) -> None:
    """`check` for routes: 409 with the owner's "edit it there" detail."""
    try:
        check(db, user_id, commitment_id, fields)
    except LinkedCommitmentEdit as refused:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refused.owner.detail) from None
