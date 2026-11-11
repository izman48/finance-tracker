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
from app.models.repayment_mark import CREATED_VIA_MCP, CREATED_VIA_WEB
from app.schemas.repayments import ClaudeMarkRequest, ClaudeUnmarkRequest
from app.services.analytics.common import _today
from app.services.planning_writes import WriteRequest, key_in_use, replay_if_applied, run_batch, run_write
from app.services.repayment_marks import lock_user_marks
from app.services.repayment_writes import PlannedMark, plan_marks, preview_figures

router = APIRouter(prefix="/planning/repayments", tags=["planning"])
_TOOL_MARK = "mark_paid_back"


@router.post("/mark")
def mark_paid_back(body: ClaudeMarkRequest, caller: RepaymentsWriter, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Mark 1 to 8 incoming payments as paid back, against a spend or a
    category. Every mark is checked before any is written; all are saved in
    one transaction, one audit row each, sharing a batch id, or none."""
    user = caller.user
    if not body.dry_run and key_in_use(db, user.id, body.idempotency_key):
        # A retry: run_batch replays the first result (or 409s a different
        # request) before anything is checked or written.
        return run_batch(db, caller, [WriteRequest(_TOOL_MARK, "repayment_mark", None, _unused)], body,
                         batch_id=uuid.uuid4())
    lock_user_marks(db, user.id)
    plans = plan_marks(db, user, body.marks, accept_warnings=body.accept_warnings, dry_run=body.dry_run)
    # Before the write, so "before" is today's figures and "after" is what the marks will show (T7).
    figures = preview_figures(db, user, plans, _today())
    created_via = CREATED_VIA_MCP if caller.grant_id else CREATED_VIA_WEB
    reqs = [_mark_write(user.id, plan, created_via) for plan in plans]
    result = run_batch(db, caller, reqs, body, batch_id=uuid.uuid4())
    result["marks"] = [
        {"credit_id": str(p.entry.credit_id), "spend_id": str(p.entry.spend_id) if p.entry.spend_id else None,
         "category": p.entry.category, "amount_pounds": f"{p.amount:.2f}", "warnings": p.warnings, **f}
        for p, f in zip(plans, figures)
    ]
    return result


def _mark_write(user_id: uuid.UUID, plan: PlannedMark, created_via: str) -> WriteRequest:
    def apply(db: Session, existing: RepaymentMark | None) -> RepaymentMark:
        if existing is not None:
            return existing  # an identical repeat: unchanged, no audit row (T-03-2 T11)
        mark = RepaymentMark(
            user_id=user_id, credit_transaction_id=plan.entry.credit_id, spend_transaction_id=plan.entry.spend_id,
            category=plan.entry.category, amount=plan.amount, label=plan.label, created_via=created_via,
        )
        db.add(mark)
        return mark
    target_id = plan.existing.id if plan.existing is not None else None
    return WriteRequest(tool=_TOOL_MARK, target_kind="repayment_mark", target_id=target_id, apply=apply)


def _unused(db: Session, target):
    raise AssertionError("a replay never applies")


@router.post("/{mark_id}/unmark")
def unmark_paid_back(mark_id: uuid.UUID, body: ClaudeUnmarkRequest, caller: RepaymentsWriter,
                     db: Annotated[Session, Depends(get_db)]) -> dict:
    """Soft-delete one active mark Claude made (`active` false)."""
    def apply(db: Session, mark: RepaymentMark) -> RepaymentMark:
        mark.active = False
        return mark

    # Amount and category as context (before == after), so the Changes page
    # can say what the unmark removed; undo checks them too.
    req = WriteRequest(tool="unmark_paid_back", target_kind="repayment_mark", target_id=mark_id, apply=apply,
                       context_fields=("amount", "category"))
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
