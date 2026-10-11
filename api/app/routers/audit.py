"""The trail of Claude's planning writes, undo (T-08-3b) and keep (T-08-20).

Web session only (`CurrentUser`): an MCP token gets 401, so an injected
assistant can neither read the trail, undo the user's own fixes, nor keep
its own changes. No route edits a row's content or deletes one: undo adds a
row and stamps `undone_at`; keep stamps `kept_at`.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.display_text import without_hidden_characters
from app.core.security import CurrentUser
from app.models import AuditEntry, CommitmentRule, OAuthClient, OAuthGrant
from app.models.audit import AUDIT_KIND_WRITE
from app.schemas import AuditEntryResponse, AuditPage
from app.services.claude_keep import KEPT, PENDING, applied_dismissals, claude_rows, keep_kind, keep_states
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
    keeps = _keep_states(db, current_user.id, page)
    return AuditPage(
        items=[_response(row, *clients.get(row.id, (None, None)), keep=keeps.get(row.id)) for row in page],
        next_cursor=page[-1].id if len(rows) > limit else None,
    )


@router.post("/{audit_id}/undo", response_model=AuditEntryResponse)
def undo_change(
    audit_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AuditEntryResponse:
    entry = undo_write(db, current_user, audit_id)
    return _response(entry, *_clients(db, [entry]).get(entry.id, (None, None)),
                     keep=_keep_states(db, current_user.id, [entry]).get(entry.id))


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


def _response(row: AuditEntry, client_name: str | None, connected_at,
              keep: tuple[str, str] | None = None) -> AuditEntryResponse:
    """`keep`: (state, kind) from `_keep_states`, or None."""
    state, kind = keep or (None, None)
    return AuditEntryResponse(
        id=row.id, created_at=row.created_at, tool=row.tool, batch_id=row.batch_id,
        client_name=client_name, connection_created_at=connected_at, target_kind=row.target_kind,
        target_id=row.target_id, target_label=row.target_label, changes=json.loads(row.changes),
        undone_at=row.undone_at, keep=state, keep_kind=kind, kept_at=row.kept_at if state == KEPT else None,
    )


def _keep_states(db: Session, user_id, rows: list[AuditEntry]) -> dict:
    """{audit id: (keep state, keep kind)} for Claude's writes to
    commitments that the keep rule holds (T-08-20, T-08-21b).
    A row's state depends on its siblings (later kept changes, hand edits),
    so each commitment's whole Claude history is read."""
    ids = {r.target_id for r in rows if r.target_kind == "commitment"}
    if not ids:
        return {}
    commitments = {
        c.id: c for c in db.query(CommitmentRule).filter(CommitmentRule.user_id == user_id, CommitmentRule.id.in_(ids))
    }
    applied = applied_dismissals(db, user_id)
    out = {}
    for target_id, history in claude_rows(db, user_id, ids).items():
        rule = commitments.get(target_id)
        for row_id, state in keep_states(rule, history, applied).items():
            if state is not None:
                out[row_id] = (state, keep_kind(rule))
    return out


@router.post("/{audit_id}/keep", response_model=AuditEntryResponse)
def keep_change(
    audit_id: uuid.UUID,
    current_user: CurrentUser,  # web session only: Claude can't keep its own change
    db: Annotated[Session, Depends(get_db)],
) -> AuditEntryResponse:
    """Keep a change Claude made that the figures hold back (T-08-20 D4,
    T-08-21b D5), so it now counts: an income raised or confirmed (savable),
    or a bill dismissed, lowered or moved later (safe to spend). Idempotent.
    409 when there is nothing to keep: a change that isn't held, undone, or
    every field Claude changed has since been set by hand."""
    entry = (
        db.query(AuditEntry)
        .filter(AuditEntry.id == audit_id, AuditEntry.user_id == current_user.id, AuditEntry.kind == AUDIT_KIND_WRITE)
        .with_for_update()
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")
    held = _keep_states(db, current_user.id, [entry]).get(entry.id)
    if held is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There is nothing to keep for this change.")
    state, kind = held
    if state == PENDING:
        entry.kept_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(entry)
    return _response(entry, *_clients(db, [entry]).get(entry.id, (None, None)), keep=(KEPT, kind))
