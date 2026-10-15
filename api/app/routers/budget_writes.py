"""Claude's budget writes over MCP (T-09-5; concept section 6; sec's T-09-5
criteria; owner D6 = No).

Every route takes `BudgetsWriter` (the finance:budgets.write scope, and the
per-user write limits shared with planning writes) and goes through the
Sprint 08 framework: dry_run by default, idempotency, an encrypted audit row
(`target_kind: "budget"`), web-only undo. Only `limit_pounds`, `paused` and
`active` change (`TARGETS["budget"]`). A budget is addressed by its id,
never by its category (untrusted text). Each change also appends to the
budget change log, as the app's own writes do (T-09-3). A limit Claude
lowers applies at once (D6). A paused or removed budget leaves the budget
line (T-09-14), and the pause, resume and remove previews say so (sec).
"""
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.planning_write import BudgetsWriter
from app.models import Budget
from app.models.budget import CREATED_VIA_MCP
from app.schemas.budgets import ClaudeBudgetActionRequest, ClaudeSetBudgetsRequest
from app.services import budgets as svc
from app.services.budget_history import ensure_baseline, record_change
from app.services.planning_writes import WriteRequest, replay_if_applied, run_batch, run_write

router = APIRouter(prefix="/planning/budgets", tags=["planning"])


@router.post("/set")
def set_budgets(body: ClaudeSetBudgetsRequest, caller: BudgetsWriter, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Create or update each listed category's budget. Every entry is checked
    (one per category, the user's purchase categories, not mostly
    commitments, the 20 cap after the change) before anything is written."""
    user = caller.user
    svc.lock_user_budgets(db, user)
    existing = {b.category: b for b in svc.active_budgets(db, user)}
    svc.validate_categories(db, user, [e.category for e in body.budgets], set(existing))
    svc.check_cap(len(existing) + sum(e.category not in existing for e in body.budgets))

    def entry_write(category: str, limit: int, budget_id) -> WriteRequest:
        def apply(db: Session, budget: Budget | None) -> Budget:
            if budget is None:
                budget = Budget(user_id=user.id, category=category, limit_pounds=Decimal(limit),
                                created_via=CREATED_VIA_MCP)
                db.add(budget)
            elif Decimal(budget.limit_pounds) == Decimal(limit):
                return budget  # unchanged: no change-log row and no audit row (sec)
            else:
                ensure_baseline(db, budget)
                budget.limit_pounds = Decimal(limit)
            record_change(db, budget)
            return budget
        return WriteRequest(tool="set_budgets", target_kind="budget", target_id=budget_id, apply=apply)

    reqs = [
        entry_write(e.category, e.limit_pounds, existing[e.category].id if e.category in existing else None)
        for e in body.budgets
    ]
    return run_batch(db, caller, reqs, body, batch_id=uuid.uuid4())


def _action(budget_id: uuid.UUID, tool: str, body: ClaudeBudgetActionRequest, caller, db: Session, change,
            effect: str) -> dict:
    def apply(db: Session, target: Budget) -> Budget:
        ensure_baseline(db, target)
        change(target, check=False)
        record_change(db, target)
        return target

    req = WriteRequest(tool=tool, target_kind="budget", target_id=budget_id, apply=apply)
    # A retry of a change that already applied replays it, before the checks
    # below would refuse it as already done (T-12-9c).
    replay = replay_if_applied(db, caller, req, body)
    if replay is not None:
        return {**replay, "effect": f"{replay['target_label']}: {effect}"}
    budget = svc.owned_budget(db, caller.user, budget_id)  # another user's, or removed: 404
    change(budget, check=True)
    result = run_write(db, caller, req, body)
    # An honest preview (sec on T-09-14): what the change does to the line.
    return {**result, "effect": f"{budget.category}: {effect}"}


def _refuse(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


@router.post("/{budget_id}/pause")
def pause_budget(budget_id: uuid.UUID, body: ClaudeBudgetActionRequest, caller: BudgetsWriter,
                 db: Annotated[Session, Depends(get_db)]) -> dict:
    """Pause: its spending counts as other spending and it leaves the budget
    line. Already paused: 422."""
    def change(budget: Budget, check: bool) -> None:
        if check:
            if budget.paused:
                raise _refuse("That budget is already paused.")
            return
        budget.paused = True
    return _action(budget_id, "pause_budget", body, caller, db, change,
                   "Active → Paused. It no longer counts in the budget line.")


@router.post("/{budget_id}/resume")
def resume_budget(budget_id: uuid.UUID, body: ClaudeBudgetActionRequest, caller: BudgetsWriter,
                  db: Annotated[Session, Depends(get_db)]) -> dict:
    """Resume a paused budget. Not paused: 422."""
    def change(budget: Budget, check: bool) -> None:
        if check:
            if not budget.paused:
                raise _refuse("That budget isn't paused.")
            return
        budget.paused = False
    return _action(budget_id, "resume_budget", body, caller, db, change,
                   "Paused → Active. It counts in the budget line again.")


@router.post("/{budget_id}/remove")
def remove_budget(budget_id: uuid.UUID, body: ClaudeBudgetActionRequest, caller: BudgetsWriter,
                  db: Annotated[Session, Depends(get_db)]) -> dict:
    """Remove (soft): kept for History; it leaves the budget line."""
    def change(budget: Budget, check: bool) -> None:
        if check:
            return
        budget.active = False
    return _action(budget_id, "remove_budget", body, caller, db, change,
                   "Removed. It no longer counts in the budget line; it stays in History.")
