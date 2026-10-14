"""Claude's commitment edits: update and dismiss (T-08-9).

Both take `PlanningWriter` (finance:planning.write, per-user limits) and go
through `run_write`: dry_run by default, idempotency, encrypted audit, undo.
Lookups are by id AND user_id (another user's commitment is 404 and nothing
is audited). The request models allow only the fields Claude may change.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ownership import require_owned_account_ids
from app.core.planning_write import PlanningWriter
from app.models import CommitmentRule, CommitmentSource, CommitmentStatus
from app.schemas import DismissCommitmentRequest, UpdateCommitmentRequest
from app.services.analytics.card_links import USER as CARD_LINK_USER
from app.services.analytics.commitments import merchant_match_key
from app.services.linked_commitments import refuse_linked_edit
from app.services.planning_writes import WriteRequest, run_write

router = APIRouter(prefix="/planning", tags=["planning"])

_FLAGS = {"dry_run", "idempotency_key", "batch_id"}

@router.post("/commitments/{commitment_id}/update")
def update_commitment(
    commitment_id: uuid.UUID,
    body: UpdateCommitmentRequest,
    caller: PlanningWriter,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_owned_account_ids(db, caller.user, body)
    updates = {f: getattr(body, f) for f in body.model_fields_set - _FLAGS}
    # A loan's repayment changes only through the loan (sec T-10-8), dry run
    # or not, and nothing is audited.
    refuse_linked_edit(db, caller.user.id, commitment_id, updates)

    def apply(db: Session, rule: CommitmentRule) -> CommitmentRule:
        relabelled = "label" in updates and updates["label"] != rule.label
        old_key = rule.match_key or merchant_match_key(rule.direction, rule.label)
        for field, value in updates.items():
            setattr(rule, field, value)
        if "card_account_id" in updates:
            rule.card_link_source = CARD_LINK_USER
        if relabelled:
            # A rule with no key matches payments by its label, so a rename
            # would quietly change what it matches (sec on #127): keep the
            # old label's key, detected or manual.
            rule.match_key = old_key
        if relabelled and rule.source == CommitmentSource.DETECTED.value:
            # sync_suggestions re-derives a detected rule's match_key from its
            # label; a manual rule's key is left alone, so its payments keep
            # matching and the merchant isn't suggested again.
            rule.source = CommitmentSource.MANUAL.value
        return rule

    req = WriteRequest(
        tool="update_commitment", target_kind="commitment", target_id=commitment_id,
        apply=apply, batch_id=body.batch_id,
    )
    return run_write(db, caller, req, body)


@router.post("/commitments/{commitment_id}/dismiss")
def dismiss_commitment(
    commitment_id: uuid.UUID,
    body: DismissCommitmentRequest,
    caller: PlanningWriter,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    # An injected Claude must not dismiss a loan repayment to raise
    # safe-to-spend (sec T-10-8).
    refuse_linked_edit(db, caller.user.id, commitment_id, {"status"})

    def apply(db: Session, rule: CommitmentRule) -> CommitmentRule:
        rule.status = CommitmentStatus.DISMISSED.value
        return rule

    req = WriteRequest(
        tool="dismiss_commitment", target_kind="commitment", target_id=commitment_id,
        apply=apply, batch_id=body.batch_id,
    )
    return run_write(db, caller, req, body)
