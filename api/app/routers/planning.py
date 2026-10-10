"""Planned events Claude can add, list and remove (T-08-6).

Writes take `PlanningWriter` (finance:planning.write, per-user rate limits)
and go through `run_write` (dry_run by default, idempotency, audit, undo).
The only thing Claude may delete is a one-off planned event it created
itself, and only softly (`active = False`), so undo can restore it.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.oauth_tokens import Caller, CurrentUserOrMcpRead
from app.core.ownership import require_owned_account_ids
from app.core.planning_write import PlanningWriter
from app.models import PlannedItem, PlannedKind
from app.schemas import AddPlannedEventRequest, PlannedEventItem, PlannedEventList, RemovePlannedEventRequest
from app.services.planning_writes import WriteRequest, claude_markers, key_in_use, run_write

router = APIRouter(prefix="/planning", tags=["planning"])

LIST_LIMIT = 200
DUPLICATE_WINDOW = timedelta(hours=24)
CREATED_VIA_MCP = "mcp"


@router.post("/planned-events")
def add_planned_event(
    body: AddPlannedEventRequest,
    caller: PlanningWriter,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_owned_account_ids(db, caller.user, body)
    # A retry with the same key replays its first result (run_write); the
    # duplicate guard is for a *fresh* key describing the same event.
    retry = not body.dry_run and key_in_use(db, caller.user.id, body.idempotency_key)
    existing = None if retry else _recent_duplicate(db, caller, body)
    if existing is not None:
        # Claude may retry with a fresh key; a second copy would double the
        # money (for income, overstate what's coming in). Nothing is written.
        return {
            "dry_run": body.dry_run, "duplicate": True, "audit_id": None, "target_kind": "planned_event",
            "target_id": str(existing.id), "target_label": existing.name, "changes": [],
        }

    def apply(db: Session, _target) -> PlannedItem:
        item = PlannedItem(
            user_id=caller.user.id, name=body.name, direction=body.direction,
            kind=PlannedKind.ONE_OFF.value, start_date=body.date, amount=body.amount,
            account_id=body.account_id, created_via=CREATED_VIA_MCP if caller.grant_id else "web",
        )
        db.add(item)
        return item

    req = WriteRequest(tool="add_planned_event", target_kind="planned_event", target_id=None, apply=apply)
    return {**run_write(db, caller, req, body), "duplicate": False}


@router.post("/planned-events/{item_id}/remove")
def remove_planned_event(
    item_id: uuid.UUID,
    body: RemovePlannedEventRequest,
    caller: PlanningWriter,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Only an active one-off item Claude created; anything else is 404."""
    removable = (
        db.query(PlannedItem.id)
        .filter(
            PlannedItem.id == item_id, PlannedItem.user_id == caller.user.id,
            PlannedItem.kind == PlannedKind.ONE_OFF.value, PlannedItem.created_via == CREATED_VIA_MCP,
            PlannedItem.active.is_(True),
        )
        .first()
    )
    if removable is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned event not found")

    def apply(db: Session, item: PlannedItem) -> PlannedItem:
        item.active = False
        return item

    req = WriteRequest(
        tool="remove_planned_event", target_kind="planned_event", target_id=item_id, apply=apply,
        context_fields=("name", "amount", "start_date", "direction"),
    )
    return {**run_write(db, caller, req, body), "duplicate": False}


@router.get("/planned-events", response_model=PlannedEventList)
def list_planned_events(
    current_user: CurrentUserOrMcpRead,
    db: Annotated[Session, Depends(get_db)],
) -> PlannedEventList:
    """The caller's active planned items (any origin), soonest first, at most 200."""
    items = (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == current_user.id, PlannedItem.active.is_(True))
        .order_by(PlannedItem.start_date, PlannedItem.id)
        .limit(LIST_LIMIT + 1)
        .all()
    )
    page = items[:LIST_LIMIT]
    markers = claude_markers(db, current_user.id, "planned_event", [i.id for i in page])
    return PlannedEventList(
        items=[{**PlannedEventItem.model_validate(i).model_dump(), "changed_by_claude": markers.get(i.id)}
               for i in page],
        truncated=len(items) > LIST_LIMIT,
    )


def _recent_duplicate(db: Session, caller: Caller, body: AddPlannedEventRequest) -> PlannedItem | None:
    """An active item Claude created in the last 24 h with the same direction,
    amount, date and name (case and spacing ignored). Compared in Python:
    name and amount are encrypted."""
    cutoff = datetime.now(timezone.utc) - DUPLICATE_WINDOW
    candidates = db.query(PlannedItem).filter(
        PlannedItem.user_id == caller.user.id, PlannedItem.created_via == CREATED_VIA_MCP,
        PlannedItem.kind == PlannedKind.ONE_OFF.value, PlannedItem.active.is_(True),
        PlannedItem.direction == body.direction, PlannedItem.start_date == body.date,
    )
    for item in candidates:
        created = item.created_at if item.created_at.tzinfo else item.created_at.replace(tzinfo=timezone.utc)
        if created >= cutoff and item.amount == body.amount and _norm(item.name) == _norm(body.name):
            return item
    return None


def _norm(name: str) -> str:
    return " ".join(name.casefold().split())
