"""Budgets (T-09-2): web session only (`CurrentUser`); Claude's tools come
in T-09-5 through the write framework. A budget is addressed by id, never by
category (untrusted text). Writes are scoped to the caller, and another
user's id is a 404. Log lines carry ids only, never a category or a limit.
"""
import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.oauth_tokens import CurrentUserOrMcpRead
from app.core.security import CurrentUser
from app.schemas import ClaudeMarker
from app.services.planning_writes import claude_markers
from app.models import Budget
from app.schemas.budgets import (
    BudgetHistoryResponse,
    BudgetListResponse,
    BudgetResponse,
    BudgetSuggestResponse,
    BulkBudgetsRequest,
    CreateBudgetRequest,
    UpdateBudgetRequest,
)
from app.services import budget_history
from app.services import budgets as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/budgets", tags=["budgets"])


def _commit(db: Session) -> None:
    """Commit, turning a lost race for a category (the partial unique index:
    another request created it first) into the same 422 as the check."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise svc._refuse("That category already has a budget.") from None


def _one(db: Session, user, budget_id: uuid.UUID) -> BudgetResponse:
    """The budget as GET /budgets shows it; 404 if it isn't there (sec)."""
    found = next((b for b in svc.budget_list(db, user).budgets if b.id == budget_id), None)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return found


@router.get("", response_model=BudgetListResponse)
def list_budgets(
    current_user: CurrentUserOrMcpRead, db: Annotated[Session, Depends(get_db)],
    include: Literal["categories"] | None = None,
) -> BudgetListResponse:
    """Web, or an MCP token with finance:read (Claude's list_budgets).
    `?include=categories` adds budgetable_categories (for Add budget).
    Writes any missing closed-cycle snapshots first (T-09-3). If that fails
    the budgets still load, and the next load retries."""
    user_id = current_user.id
    try:
        budget_history.write_snapshots(db, current_user)
    except Exception as exc:
        db.rollback()  # the list below needs a clean transaction
        # The type only: a message could carry a category or an amount.
        logger.error("Budget snapshots not written for user %s (%s)", user_id, type(exc).__name__)
    budgets = svc.active_budgets(db, current_user)
    markers = {
        bid: ClaudeMarker(**m) for bid, m in
        claude_markers(db, current_user.id, "budget", [b.id for b in budgets]).items()
    }
    return svc.budget_list(db, current_user, markers=markers, include_categories=include == "categories")


@router.get("/history", response_model=BudgetHistoryResponse)
def budget_history_view(
    current_user: CurrentUser, db: Annotated[Session, Depends(get_db)],
    cycles: Annotated[int, Query(ge=1, le=budget_history.HISTORY_MAX_CYCLES)] = 6,
    before: date | None = None,
) -> BudgetHistoryResponse:
    """Completed cycles (oldest first), at most 12, ending before `before`
    for older pages. Writes missing snapshots, once each, with your key."""
    return BudgetHistoryResponse(**budget_history.history(db, current_user, cycles, before))


@router.post("", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED)
def create_budget(
    body: CreateBudgetRequest, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)],
) -> BudgetResponse:
    svc.lock_user_budgets(db, current_user)
    svc.validate_categories(db, current_user, [body.category])
    existing = svc.active_budgets(db, current_user)
    if any(b.category == body.category for b in existing):
        raise svc._refuse("That category already has a budget.")
    svc.check_cap(len(existing) + 1)
    budget = Budget(user_id=current_user.id, category=body.category, limit_pounds=Decimal(body.limit_pounds))
    db.add(budget)
    budget_history.record_change(db, budget)
    _commit(db)
    logger.info("Budget %s created for user %s", budget.id, current_user.id)
    return _one(db, current_user, budget.id)


@router.patch("/{budget_id}", response_model=BudgetResponse)
def update_budget(
    budget_id: uuid.UUID, body: UpdateBudgetRequest, current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> BudgetResponse:
    budget = svc.owned_budget(db, current_user, budget_id)
    if body.limit_pounds is not None:
        budget.limit_pounds = Decimal(body.limit_pounds)
    if body.paused is not None and body.paused != budget.paused:
        if body.paused:
            svc.hold(db, current_user, budget)
        else:
            svc.release_hold(budget)
        budget.paused = body.paused
    budget_history.record_change(db, budget)
    db.commit()
    return _one(db, current_user, budget.id)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_budget(
    budget_id: uuid.UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)],
) -> Response:
    budget = svc.owned_budget(db, current_user, budget_id)
    if not budget.paused:
        svc.hold(db, current_user, budget)
    budget.active = False  # kept for History
    budget_history.record_change(db, budget)
    db.commit()
    logger.info("Budget %s removed for user %s", budget.id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("", response_model=BudgetListResponse)
def set_budgets(
    body: BulkBudgetsRequest, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)],
) -> BudgetListResponse:
    """Create or update each listed category's budget, all or nothing: every
    entry is checked (categories, duplicates, the cap after the change)
    before anything is written, then one commit writes them all. A new
    category must be the user's own and not mostly commitments; an existing
    budget's limit can be changed even if its category has since become
    mostly commitments. Budget writes are serialised per user (the user
    row, FOR UPDATE), so the 20 cap holds under concurrency."""
    svc.lock_user_budgets(db, current_user)
    existing = {b.category: b for b in svc.active_budgets(db, current_user)}
    svc.validate_categories(db, current_user, [e.category for e in body.budgets], set(existing))
    new = [e for e in body.budgets if e.category not in existing]
    svc.check_cap(len(existing) + len(new))
    for entry in body.budgets:
        budget = existing.get(entry.category)
        if budget is not None:
            budget.limit_pounds = Decimal(entry.limit_pounds)
        else:
            budget = Budget(user_id=current_user.id, category=entry.category, limit_pounds=Decimal(entry.limit_pounds))
            db.add(budget)
        budget_history.record_change(db, budget)
    _commit(db)
    return svc.budget_list(db, current_user)


@router.post("/nudges/{nudge_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_budget_nudge(
    nudge_id: uuid.UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Web only. Another user's or an unknown nudge is a 404."""
    svc.dismiss_nudge(db, current_user, nudge_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/suggest", response_model=BudgetSuggestResponse)
def suggest_budgets(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> BudgetSuggestResponse:
    """Dry: reads only."""
    return svc.suggest(db, current_user)
