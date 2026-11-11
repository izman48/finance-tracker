"""Claude's paid-back writes over MCP (T-03-3 P5; PRD "MCP contract").

Every route takes `RepaymentsWriter` (the finance:repayments.write scope,
and the per-user write limits shared with every write) and goes through the
Sprint 08 framework: dry_run by default, idempotency, one encrypted audit
row per mark (`target_kind: "repayment_mark"`), web-only undo. Mark writes
take `lock_user_marks` before any mark row, as undo does, so caps checked
here can't be raced. Claude may unmark only marks it made (T-03-2 T2); any
other id, another user's included, is a 404 that never says whose.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.planning_write import RepaymentsWriter
from app.models import RepaymentMark
from app.models.repayment_mark import CREATED_VIA_MCP
from app.schemas.repayments import ClaudeUnmarkRequest
from app.services.planning_writes import WriteRequest, replay_if_applied, run_write
from app.services.repayment_marks import lock_user_marks

router = APIRouter(prefix="/planning/repayments", tags=["planning"])


@router.post("/{mark_id}/unmark")
def unmark_paid_back(mark_id: uuid.UUID, body: ClaudeUnmarkRequest, caller: RepaymentsWriter,
                     db: Annotated[Session, Depends(get_db)]) -> dict:
    """Soft-delete one active mark Claude made (`active` false)."""
    def apply(db: Session, mark: RepaymentMark) -> RepaymentMark:
        mark.active = False
        return mark

    req = WriteRequest(tool="unmark_paid_back", target_kind="repayment_mark", target_id=mark_id, apply=apply)
    # A retry of an unmark that already applied replays it, before the check
    # below would call the mark not found (T-12-9c).
    replay = replay_if_applied(db, caller, req, body)
    if replay is not None:
        return replay
    lock_user_marks(db, caller.user.id)
    mark = (
        db.query(RepaymentMark)
        .filter(RepaymentMark.id == mark_id, RepaymentMark.user_id == caller.user.id,
                RepaymentMark.active.is_(True), RepaymentMark.created_via == CREATED_VIA_MCP)
        .first()
    )
    if mark is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return run_write(db, caller, req, body)
