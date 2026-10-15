"""A holding's monthly contribution as one linked commitment (T-11-3c,
ADR-002 sections 3-4).

The holding is the source of truth: its commitment's amount and next date
follow what the user sets on the holding, and the shared guard
(`linked_commitments`) refuses edits elsewhere. Every link field is set
here, never from a request. An existing bill is taken over only when the
user picked it (owner D2: even a single match is a choice). Candidate
matching runs in Python because amounts are encrypted.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from app.models import (
    Asset,
    AssetValuation,
    CommitmentDirection,
    CommitmentRule,
    CommitmentSource,
    CommitmentStatus,
)
from app.models.commitment_link import CONTRIBUTION, CommitmentLink
from app.services.linked_commitments import linked_commitment_ids

NEW = "new"
LinkResult = Literal["created", "linked"]
MONTHLY = "monthly"


class ChooseCommitment(Exception):
    """Existing bills could be this contribution, or the client's choice
    isn't one of them: the user picks (D2)."""

    def __init__(self, candidates: list[CommitmentRule]):
        self.candidates = candidates
        super().__init__("choose_commitment")


def candidates(db: Session, asset: Asset, amount: Decimal) -> list[CommitmentRule]:
    """The caller's monthly expense bills of this amount, or whose label
    names the holding (ux A7), that aren't dismissed, tied to a card, or
    linked to anything else."""
    name = asset.name.casefold()
    taken = linked_commitment_ids(db, asset.user_id)
    rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == asset.user_id,
            CommitmentRule.direction == CommitmentDirection.EXPENSE.value,
            CommitmentRule.status != CommitmentStatus.DISMISSED.value,
            CommitmentRule.card_account_id.is_(None),
            CommitmentRule.cadence == MONTHLY,
        )
        .all()
    )
    return sorted(
        (
            r for r in rules
            if r.id not in taken and (Decimal(str(r.amount)) == amount or name in r.label.casefold())
        ),
        key=lambda r: (r.label.casefold(), str(r.id)),
    )


def link(db: Session, asset: Asset, choice: str | None, amount: Decimal, next_date: date,
         today: date, account_id: uuid.UUID | None = None) -> tuple[CommitmentRule, LinkResult]:
    """Opt in; returns the bill and whether it was created or taken over.
    Raises ChooseCommitment, before anything is written, when an
    existing bill matches and the user hasn't chosen, or chose something
    that isn't a candidate."""
    options = candidates(db, asset, amount)
    if choice == NEW or (choice is None and not options):
        rule, result = _new_commitment(db, asset), "created"
    else:
        rule = next((r for r in options if str(r.id) == choice), None)
        if rule is None:
            raise ChooseCommitment(options)
        result = "linked"
    rule.status = CommitmentStatus.CONFIRMED.value
    asset.commitment_link = CommitmentLink(
        user_id=asset.user_id, commitment_id=rule.id, role=CONTRIBUTION,
        commitment_created=result == "created", created_on=today,
    )
    # Never both (sec): the bill now carries the contribution.
    asset.monthly_contribution = None
    sync(rule, amount, next_date, account_id)
    return rule, result


def _new_commitment(db: Session, asset: Asset) -> CommitmentRule:
    rule = CommitmentRule(
        id=uuid.uuid4(), user_id=asset.user_id, direction=CommitmentDirection.EXPENSE.value,
        label=f"{asset.name} contribution", source=CommitmentSource.MANUAL.value,
        status=CommitmentStatus.CONFIRMED.value,
    )
    db.add(rule)
    return rule


def sync(rule: CommitmentRule, amount: Decimal, next_date: date, account_id: uuid.UUID | None = None) -> None:
    """The bill follows the holding (rule 4). `account_id` (already
    ownership-checked) changes the pay-from account when given."""
    if account_id is not None:
        rule.account_id = account_id
    rule.amount = amount
    rule.cadence = MONTHLY
    rule.interval_days = None
    rule.interval_months = None
    rule.next_date = next_date
    rule.ends_on = None


def linked_rule(db: Session, asset: Asset) -> CommitmentRule | None:
    link_row = asset.commitment_link
    if link_row is None:
        return None
    return (
        db.query(CommitmentRule)
        .filter(CommitmentRule.id == link_row.commitment_id, CommitmentRule.user_id == asset.user_id)
        .first()
    )


def remove(db: Session, asset: Asset, value_today: Decimal | None, today: date) -> None:
    """Opt out (rule 3), in the caller's transaction. Today's value (which
    includes contributions assumed paid) is stored as a valuation first, so
    net worth doesn't step down overnight. The bill is deleted only if the
    link created it; a bill the user already had stays, unguarded."""
    rule = linked_rule(db, asset)
    created = asset.commitment_link.commitment_created
    if rule is not None:
        # ux: the monthly contribution stays on the investment.
        asset.monthly_contribution = Decimal(str(rule.amount))
    if value_today is not None:
        _value_today(db, asset, value_today, today)
    asset.commitment_link = None
    db.flush()
    if rule is not None and created:
        db.delete(rule)


def _value_today(db: Session, asset: Asset, value: Decimal, today: date) -> None:
    same_day = next((v for v in asset.valuations if v.valued_at == today), None)
    if same_day is not None:
        same_day.value = value
    else:
        db.add(AssetValuation(asset_id=asset.id, value=value, valued_at=today))

