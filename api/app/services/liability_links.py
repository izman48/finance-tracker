"""A liability's repayment as one linked commitment (T-10-8; spec stage 2).

The liability is the source of truth: its linked commitment's amount,
cadence, next date and end follow the liability's schedule. The link is the
stored `Liability.linked_commitment_id`, set only here, never matched by
label, with a matching `commitment_links` row written in the same
transaction (ADR-002): its UNIQUE(commitment_id) keeps a bill linked to at
most one loan or holding. Every lookup is scoped to the caller, and candidate matching runs in
Python because amounts are encrypted.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from app.models import (
    CommitmentDirection,
    CommitmentRule,
    CommitmentSource,
    CommitmentStatus,
    Liability,
)
from app.models.commitment_link import REPAYMENT, CommitmentLink
from app.services.liabilities import derived_figures
from app.services.linked_commitments import linked_commitment_ids

# Liability cadence -> (commitment cadence, interval_days).
COMMITMENT_CADENCE = {
    "monthly": ("monthly", None),
    "weekly": ("weekly", None),
    "fortnightly": ("custom_days", 14),
    "four_weekly": ("custom_days", 28),
}
NEW = "new"
LinkResult = Literal["created", "linked"]


class ChooseCommitment(Exception):
    """More than one existing commitment could be this repayment, or the
    client's choice isn't one of them: the user picks (ux A7)."""

    def __init__(self, candidates: list[CommitmentRule]):
        self.candidates = candidates
        super().__init__("choose_commitment")


def candidates(db: Session, liability: Liability) -> list[CommitmentRule]:
    """The caller's expense commitments this repayment could be: same amount
    and cadence, not dismissed, not already linked to another liability."""
    cadence, interval_days = COMMITMENT_CADENCE[liability.cadence]
    taken = _linked_ids(db, liability.user_id) - {liability.linked_commitment_id}
    rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == liability.user_id,
            CommitmentRule.direction == CommitmentDirection.EXPENSE.value,
            CommitmentRule.status != CommitmentStatus.DISMISSED.value,
            # A card repayment is never a loan's repayment (lead, eng-a on #181).
            CommitmentRule.card_account_id.is_(None),
        )
        .all()
    )
    return sorted(
        (
            r for r in rules
            if r.id not in taken
            and Decimal(str(r.amount)) == liability.payment
            and r.cadence == cadence
            and (interval_days is None or r.interval_days == interval_days)
        ),
        key=lambda r: (r.label.casefold(), str(r.id)),
    )


def _linked_ids(db: Session, user_id: uuid.UUID) -> set:
    return linked_commitment_ids(db, user_id)


def link(db: Session, liability: Liability, choice: str | None, today: date) -> LinkResult:
    """Link the liability's repayment (rules 1 and 2). Returns "linked" when
    an existing commitment was taken over, "created" for a new one. Raises
    ChooseCommitment when the user must pick, before anything is written."""
    options = candidates(db, liability)
    rule: CommitmentRule | None
    result: LinkResult
    if choice == NEW or (choice is None and not options):
        rule, result = _new_commitment(db, liability), "created"
    elif choice is None and len(options) == 1:
        rule, result = options[0], "linked"
    else:
        rule = next((r for r in options if str(r.id) == choice), None)
        if rule is None:
            raise ChooseCommitment(options)
        result = "linked"
    rule.status = CommitmentStatus.CONFIRMED.value
    liability.linked_commitment_id = rule.id
    liability.commitment_created = result == "created"
    liability.commitment_link = CommitmentLink(
        user_id=liability.user_id, commitment_id=rule.id, role=REPAYMENT,
        commitment_created=liability.commitment_created, created_on=today,
    )
    sync(liability, rule, today)
    return result


def _new_commitment(db: Session, liability: Liability) -> CommitmentRule:
    # The id is set here because the row is only flushed once `sync` has
    # filled its required fields.
    rule = CommitmentRule(
        id=uuid.uuid4(),
        user_id=liability.user_id,
        direction=CommitmentDirection.EXPENSE.value,
        label=liability.lender,
        source=CommitmentSource.MANUAL.value,
        status=CommitmentStatus.CONFIRMED.value,
    )
    db.add(rule)
    return rule


def sync(liability: Liability, rule: CommitmentRule, today: date) -> None:
    """Make the commitment follow the liability (rule 4) and end after the
    final scheduled payment (rule 5)."""
    if liability.payment is None:  # only linked while there is a payment
        return
    figures = derived_figures(liability, today, linked=True)
    cadence, interval_days = COMMITMENT_CADENCE[liability.cadence]
    rule.amount = liability.payment
    rule.cadence = cadence
    rule.interval_days = interval_days
    rule.interval_months = None
    rule.next_date = figures["next_payment_date"] or figures["payoff_date"]
    rule.ends_on = figures["payoff_date"]
    if liability.commitment_created:
        rule.label = liability.lender


def linked_rule(db: Session, liability: Liability) -> CommitmentRule | None:
    if liability.linked_commitment_id is None:
        return None
    return (
        db.query(CommitmentRule)
        .filter(CommitmentRule.id == liability.linked_commitment_id, CommitmentRule.user_id == liability.user_id)
        .first()
    )


def remove(db: Session, liability: Liability) -> None:
    """Opt-out (rule 3), in the caller's transaction: unlink, and delete the
    commitment only if the liability created it. A bill the user already had
    stays as an ordinary bill with no end."""
    rule = linked_rule(db, liability)
    created = liability.commitment_created
    liability.linked_commitment_id = None
    liability.commitment_created = False
    liability.commitment_link = None
    db.flush()
    if rule is None:
        return
    if created:
        db.delete(rule)
    else:
        rule.ends_on = None


def release(db: Session, liability: Liability) -> None:
    """Deleting the liability without opting out keeps its commitment as an
    ordinary bill with no end, so the payment is still forecast (owner D4)."""
    rule = linked_rule(db, liability)
    if rule is not None:
        rule.ends_on = None
