"""The trail of Claude's planning writes, and undo (T-08-3b).

Web session only (`CurrentUser`): an MCP token gets 401, so an injected
assistant can neither read the trail nor undo the user's own fixes. There is
no route that edits or deletes audit rows.
"""
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.display_text import without_hidden_characters
from app.core.security import CurrentUser
from app.models import AuditEntry, OAuthClient, OAuthGrant
from app.models.audit import AUDIT_KIND_WRITE
from app.schemas import AuditEntryResponse, AuditPage
from app.services.planning_writes import undo_write

router = APIRouter(prefix="/audit", tags=["audit"])

PAGE_SIZE = 50


@router.get("", response_model=AuditPage)
def list_changes(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=PAGE_SIZE)] = PAGE_SIZE,
    cursor: uuid.UUID | None = None,
) -> AuditPage:
    """The caller's writes, newest first. Undo rows are left out: the write
    they undid carries `undone_at` instead."""
    query = db.query(AuditEntry).filter(
        AuditEntry.user_id == current_user.id, AuditEntry.kind == AUDIT_KIND_WRITE
    )
    if cursor is not None:
        after = query.filter(AuditEntry.id == cursor).first()
        if after is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")
        query = query.filter(or_(
            AuditEntry.created_at < after.created_at,
            and_(AuditEntry.created_at == after.created_at, AuditEntry.id < after.id),
        ))
    rows = query.order_by(AuditEntry.created_at.desc(), AuditEntry.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    clients = _clients(db, page)
    return AuditPage(
        items=[_response(row, *clients.get(row.id, (None, None))) for row in page],
        next_cursor=page[-1].id if len(rows) > limit else None,
    )


@router.post("/{audit_id}/undo", response_model=AuditEntryResponse)
def undo_change(
    audit_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AuditEntryResponse:
    entry = undo_write(db, current_user, audit_id)
    return _response(entry, *_clients(db, [entry]).get(entry.id, (None, None)))


def _clients(db: Session, rows: list[AuditEntry]) -> dict:
    """{audit id: (client name, connection created at)}, from the grant stored
    on each row (revoked grants included), never from anything a request sent.
    Falls back to the row's client id when the grant row is gone."""
    grant_ids = {r.grant_id for r in rows if r.grant_id}
    grants = {g.id: g for g in db.query(OAuthGrant).filter(OAuthGrant.id.in_(grant_ids))} if grant_ids else {}
    client_ids = {g.client_id for g in grants.values()} | {r.client_id for r in rows if r.client_id}
    names = (
        {c.client_id: c.client_name for c in db.query(OAuthClient).filter(OAuthClient.client_id.in_(client_ids))}
        if client_ids else {}
    )
    out = {}
    for r in rows:
        grant = grants.get(r.grant_id)
        name = names.get(grant.client_id if grant else r.client_id)
        if name is not None or grant is not None:
            out[r.id] = (without_hidden_characters(name) if name else None, grant.created_at if grant else None)
    return out


def _response(row: AuditEntry, client_name: str | None, connected_at) -> AuditEntryResponse:
    return AuditEntryResponse(
        id=row.id, created_at=row.created_at, tool=row.tool, batch_id=row.batch_id,
        client_name=client_name, connection_created_at=connected_at, target_kind=row.target_kind,
        target_id=row.target_id, target_label=row.target_label, changes=json.loads(row.changes),
        undone_at=row.undone_at,
    )
