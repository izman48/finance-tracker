"""Run one of Claude's planning writes safely (T-08-3b).

Every planning write route builds a `WriteRequest` and calls `run_write`:

- **dry_run** runs the real change inside a savepoint, computes the diff and
  rolls back, so the preview is the code path that will apply, and nothing
  (row, audit row or idempotency record) is written.
- **apply** claims the idempotency key first (a unique row in the same
  transaction, so a second worker waits and then replays), makes the change,
  and records an append-only, DEK-encrypted audit row whose grant and client
  come from the verified `Caller`.
- the diff covers only each target's allow-listed fields, and a write that
  changes any other column of an existing target is refused outright, so no
  change escapes the audit trail and undo.
- a write that would change nothing (re-confirming a confirmed commitment,
  dismissing a dismissed one) returns `unchanged: true` and records nothing:
  no audit row, no idempotency record, nothing to undo.
- `dry_run` and the idempotency key are read from the route's validated
  `PlanningWriteRequest` body and nowhere else, the same source
  `PlanningWriter` charges the rate limit from.
"""
import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.oauth_tokens import Caller
from app.models import AuditEntry, Budget, CommitmentRule, PlannedItem, WriteIdempotency
from app.models.audit import AUDIT_KIND_UNDO, AUDIT_KIND_WRITE
from app.schemas import PlanningWriteRequest
from app.services.linked_commitments import refuse_linked_edit

IDEMPOTENCY_TTL = timedelta(hours=24)
# Maintained by the database, not by a write.
_BOOKKEEPING_COLUMNS = frozenset({"updated_at"})


class DisallowedChange(RuntimeError):
    """A write's apply changed a column outside its target's allow-list.
    A bug in the tool, not user input: the whole write is rolled back."""


@dataclass(frozen=True)
class TargetSpec:
    model: type
    label_field: str
    # What a write may change and the diff shows, each with the parser that
    # turns its audited (JSON) form back into a column value for undo.
    fields: dict[str, Callable[[Any], Any]]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.fields)


TARGETS: dict[str, TargetSpec] = {
    "planned_event": TargetSpec(PlannedItem, "name", {
        "name": str, "direction": str, "amount": Decimal, "start_date": date.fromisoformat,
        "account_id": uuid.UUID, "active": bool,
    }),
    "commitment": TargetSpec(CommitmentRule, "label", {
        "label": str, "amount": Decimal, "cadence": str, "interval_days": int, "interval_months": int,
        "next_date": date.fromisoformat, "status": str,
        # The card link (T-08-8): a link set here is the user's ("user"), which
        # the request-time linker never changes.
        "card_account_id": uuid.UUID, "card_link_source": str,
        # A relabelled detected commitment becomes "manual", so sync_suggestions
        # stops re-keying it from its label (T-08-9's match_key trap); one
        # with no stored key gets the old label's, so its payments still match.
        "source": str, "match_key": str,
    }),
    # Claude's budget writes (T-09-5): the limit, pause and remove only (sec).
    "budget": TargetSpec(Budget, "category", {"limit_pounds": Decimal, "paused": bool, "active": bool}),
}


@dataclass(frozen=True)
class WriteRequest:
    tool: str
    target_kind: str
    target_id: uuid.UUID | None  # None: the write creates its target
    apply: Callable[[Session, Any], Any]  # (db, loaded target or None) -> target; never commits
    batch_id: uuid.UUID | None = field(default=None)
    # Allow-listed fields shown in the diff even when unchanged (before ==
    # after), so the trail says what a removal removed. Undo also checks them.
    context_fields: tuple[str, ...] = ()


def run_write(db: Session, caller: Caller, req: WriteRequest, body: PlanningWriteRequest) -> dict:
    spec = TARGETS[req.target_kind]
    idempotency_key = body.idempotency_key
    if body.dry_run:
        savepoint = db.begin_nested()
        try:
            target, label, changes = _change(db, caller, spec, req)
        finally:
            savepoint.rollback()
        if not _changes_anything(changes):
            return _unchanged(req, label, dry_run=True)
        return _result(None, None, req.target_kind, label, changes, dry_run=True)

    request_hash = _request_hash(req, body)
    replay = _claim_key(db, caller, idempotency_key, request_hash)
    if replay is not None:
        return replay
    try:
        target, label, changes = _change(db, caller, spec, req)
        if not _changes_anything(changes):
            # Nothing to record or undo; the key isn't kept either, so a later
            # call with it that does change something is treated as new.
            db.rollback()
            return _unchanged(req, label, dry_run=False)
        entry = AuditEntry(
            user_id=caller.user.id, kind=AUDIT_KIND_WRITE, tool=req.tool, target_kind=req.target_kind,
            target_id=target.id, target_label=label, changes=json.dumps(changes),
            created_target=req.target_id is None, grant_id=caller.grant_id, client_id=caller.client_id,
            batch_id=req.batch_id,
        )
        db.add(entry)
        db.flush()
        db.query(WriteIdempotency).filter(
            WriteIdempotency.user_id == caller.user.id, WriteIdempotency.key == idempotency_key
        ).update({WriteIdempotency.audit_id: entry.id})
        db.commit()
    except Exception:
        # Nothing half-done survives: not the change, the audit row or the key.
        db.rollback()
        raise
    return _entry_result(entry)


def replay_if_applied(db: Session, caller: Caller, req: WriteRequest, body: PlanningWriteRequest) -> dict | None:
    """The stored result when this exact request already applied under this
    key (T-12-9c), else None. Routes that check their target before
    `run_write` call it first, so a retry of an applied write replays instead
    of failing the check ("already paused", "not found"). The same key with a
    different request is a 409. Reads only: a new key is claimed by
    `run_write` as before."""
    if body.dry_run:
        return None
    # Scoped to the caller (another user's key never matches) and within the
    # idempotency TTL, as `_claim_key` forgets older keys.
    existing = (
        db.query(WriteIdempotency)
        .filter(
            WriteIdempotency.user_id == caller.user.id, WriteIdempotency.key == body.idempotency_key,
            WriteIdempotency.created_at >= datetime.now(timezone.utc) - IDEMPOTENCY_TTL,
        )
        .first()
    )
    if existing is None:
        return None
    return _entry_result(_stored_entry(db, caller, existing, _request_hash(req, body)))


def run_batch(db: Session, caller: Caller, reqs: list[WriteRequest], body: PlanningWriteRequest,
              batch_id: uuid.UUID) -> dict:
    """Several writes as one: all applied in one transaction with one audit
    row each, sharing `batch_id`, or none (T-09-5 set_budgets). The caller
    validates every entry first. dry_run previews all and writes nothing.
    One idempotency key covers the batch; a retry replays every audited
    row. Entries that changed nothing have no audit row, so a replay lists
    only the entries that changed."""
    if body.dry_run:
        savepoint = db.begin_nested()
        try:
            results = [_change(db, caller, TARGETS[r.target_kind], r) for r in reqs]
        finally:
            savepoint.rollback()
        return _batch_result(None, [
            _result(None, None, r.target_kind, label, changes, dry_run=True, unchanged=not _changes_anything(changes))
            for r, (_, label, changes) in zip(reqs, results)
        ], dry_run=True)

    material = WriteRequest(tool=reqs[0].tool, target_kind=reqs[0].target_kind, target_id=None,
                            apply=reqs[0].apply, batch_id=None)
    replay = _claim_key(db, caller, body.idempotency_key, _request_hash(material, body), batch=True)
    if replay is not None:
        return replay
    try:
        results, first = [], None
        for r in reqs:
            target, label, changes = _change(db, caller, TARGETS[r.target_kind], r)
            if not _changes_anything(changes):
                results.append(_result(None, target.id, r.target_kind, label, [], dry_run=False, unchanged=True))
                continue
            entry = AuditEntry(
                user_id=caller.user.id, kind=AUDIT_KIND_WRITE, tool=r.tool, target_kind=r.target_kind,
                target_id=target.id, target_label=label, changes=json.dumps(changes),
                created_target=r.target_id is None, grant_id=caller.grant_id, client_id=caller.client_id,
                batch_id=batch_id,
            )
            db.add(entry)
            db.flush()
            first = first or entry
            results.append(_entry_result(entry))
        if first is None:
            db.rollback()
            return _batch_result(None, results, dry_run=False)
        db.query(WriteIdempotency).filter(
            WriteIdempotency.user_id == caller.user.id, WriteIdempotency.key == body.idempotency_key
        ).update({WriteIdempotency.audit_id: first.id})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _batch_result(batch_id, results, dry_run=False)


def _batch_result(batch_id, results: list[dict], *, dry_run: bool) -> dict:
    return {
        "dry_run": dry_run, "batch_id": str(batch_id) if batch_id else None,
        "unchanged": all(r["unchanged"] for r in results), "results": results,
    }


def _replay_batch(db: Session, entry: AuditEntry) -> dict:
    rows = (
        db.query(AuditEntry)
        .filter(AuditEntry.user_id == entry.user_id, AuditEntry.batch_id == entry.batch_id,
                AuditEntry.kind == AUDIT_KIND_WRITE)
        .order_by(AuditEntry.created_at, AuditEntry.id)
        .all()
    )
    return _batch_result(entry.batch_id, [_entry_result(r) for r in rows], dry_run=False)


def _change(db: Session, caller: Caller, spec: TargetSpec, req: WriteRequest):
    """Apply the change (uncommitted); return (target, label, changes)."""
    target = None
    before = dict.fromkeys(spec.names)
    if req.target_id is not None:
        target = _load_target(db, spec, req.target_id, caller.user.id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        before = _snapshot(target, spec)
        columns_before = _all_columns(target)
    target = req.apply(db, target)
    db.flush()
    after = _snapshot(target, spec)
    if req.target_id is not None:
        moved = {
            k for k, v in _all_columns(target).items()
            if v != columns_before[k] and k not in spec.fields
            and k not in _BOOKKEEPING_COLUMNS
        }
        if moved:
            raise DisallowedChange(f"{req.tool} changed columns outside its allow-list: {sorted(moved)}")
    changes = [
        {"field": f, "before": before[f], "after": after[f]}
        for f in spec.names if before[f] != after[f] or f in req.context_fields
    ]
    return target, getattr(target, spec.label_field), changes


def _claim_key(db: Session, caller: Caller, key: str, request_hash: str, batch: bool = False) -> dict | None:
    """Insert the (user, key) record, or return the earlier result for it.

    The insert happens before the change, so a concurrent request with the
    same key blocks on the unique index until this transaction ends, then
    replays. Same key with a different request: 409.
    """
    cutoff = datetime.now(timezone.utc) - IDEMPOTENCY_TTL
    db.query(WriteIdempotency).filter(
        WriteIdempotency.user_id == caller.user.id, WriteIdempotency.created_at < cutoff
    ).delete(synchronize_session=False)
    db.add(WriteIdempotency(user_id=caller.user.id, key=key, request_hash=request_hash))
    try:
        db.flush()
        return None
    except IntegrityError:
        db.rollback()
    existing = (
        db.query(WriteIdempotency)
        .filter(WriteIdempotency.user_id == caller.user.id, WriteIdempotency.key == key)
        .one()
    )
    entry = _stored_entry(db, caller, existing, request_hash)
    return _replay_batch(db, entry) if batch else _entry_result(entry)


def _stored_entry(db: Session, caller: Caller, existing: WriteIdempotency, request_hash: str) -> AuditEntry:
    """The audit row an earlier request under this key wrote; 409 if that
    request was different or is still being applied."""
    if not hmac.compare_digest(existing.request_hash, request_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This idempotency_key was already used for a different request.",
        )
    entry = db.get(AuditEntry, existing.audit_id) if existing.audit_id else None
    if entry is None or entry.user_id != caller.user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That request is still being applied.")
    return entry


def _request_hash(req: WriteRequest, body: PlanningWriteRequest) -> str:
    """Of the whole validated request bar the two flags. Keyed, so the stored
    hash of a low-entropy payload (a name and an amount) can't be
    brute-forced from a database copy."""
    payload = body.model_dump(mode="json", exclude={"dry_run", "idempotency_key"})
    material = json.dumps(
        {"tool": req.tool, "target": str(req.target_id), "payload": payload, "batch": str(req.batch_id)},
        sort_keys=True, default=str,
    )
    return hmac.new(get_settings().secret_key.encode(), material.encode(), hashlib.sha256).hexdigest()


def _all_columns(target) -> dict:
    return {attr.key: getattr(target, attr.key) for attr in inspect(target).mapper.column_attrs}


def _load_target(db: Session, spec: TargetSpec, target_id: uuid.UUID, user_id: uuid.UUID, *, lock=False):
    query = db.query(spec.model).filter(spec.model.id == target_id, spec.model.user_id == user_id)
    return (query.with_for_update() if lock else query).first()


def _snapshot(target, spec: TargetSpec) -> dict:
    return {f: _plain(getattr(target, f)) for f in spec.names}


def _plain(value):
    """A JSON-safe form of a column value, for diffs and the audit row."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, uuid.UUID)):
        return str(value) if isinstance(value, uuid.UUID) else value.isoformat()
    return value


def _entry_result(entry: AuditEntry) -> dict:
    return _result(entry.id, entry.target_id, entry.target_kind, entry.target_label,
                   json.loads(entry.changes), dry_run=False)


def _changes_anything(changes: list[dict]) -> bool:
    """Context entries (before == after) alone don't make a change."""
    return any(c["before"] != c["after"] for c in changes)


def _unchanged(req: WriteRequest, label, *, dry_run: bool) -> dict:
    """The answer to a write that would change nothing (e.g. dismissing an
    already-dismissed commitment): not an error, so the assistant doesn't
    retry, and no audit row, idempotency record or undo."""
    return _result(None, req.target_id, req.target_kind, label, [], dry_run=dry_run, unchanged=True)


def _result(audit_id, target_id, target_kind, label, changes, *, dry_run: bool, unchanged: bool = False) -> dict:
    return {
        "dry_run": dry_run,
        "unchanged": unchanged,
        "audit_id": str(audit_id) if audit_id else None,
        "target_kind": target_kind,
        "target_id": str(target_id) if target_id else None,
        "target_label": label,
        "changes": changes,
    }


def undo_write(db: Session, user, audit_id: uuid.UUID) -> AuditEntry:
    """Restore the before-state of one of the user's writes.

    Only the fields that write changed are compared and restored, so changes
    made since to other fields (sync advancing `next_date`) don't block it.
    409 if any of those fields changed since, or the target is gone. Undoing
    an add soft-deletes (`active = False`); a remove was itself a soft delete,
    so undoing it re-activates. Undoing twice is a no-op. The original row is
    kept and marked; the undo is recorded as its own row.
    """
    entry = (
        db.query(AuditEntry)
        .filter(AuditEntry.id == audit_id, AuditEntry.user_id == user.id, AuditEntry.kind == AUDIT_KIND_WRITE)
        .with_for_update()
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")
    if entry.undone_at is not None:
        return entry

    spec = TARGETS[entry.target_kind]
    if entry.created_target and "active" not in spec.fields:
        # Nothing to soft-delete it with; refuse rather than hard-delete.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Can't undo this kind of change.")
    target = _load_target(db, spec, entry.target_id, user.id, lock=True)
    if target is None or getattr(target, "deleted_at", None) is not None:
        # Gone, or deleted by the user on the web (T-12-9b): an undo never
        # brings back what the user deleted.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Can't undo: the item no longer exists.")
    changes = json.loads(entry.changes)
    if entry.target_kind == "commitment":
        # A loan's repayment changes only through the loan (T-10-8).
        refuse_linked_edit(db, user.id, entry.target_id, {c["field"] for c in changes})
    current = _snapshot(target, spec)
    if any(current[c["field"]] != c["after"] for c in changes):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Can't undo: it has changed since.")

    restore = [{"field": "active", "before": True, "after": False}] if entry.created_target else [
        {"field": c["field"], "before": c["after"], "after": c["before"]} for c in changes
    ]
    for c in restore:
        parse = spec.fields[c["field"]]
        setattr(target, c["field"], None if c["after"] is None else parse(c["after"]))
    if entry.target_kind == "budget":
        # The budget change log sees undos too (T-09-3, lead on #160). A
        # budget with no log yet gets the state the undo restores as its
        # baseline: that state was in force from its creation (eng-a on #160).
        from app.services.budget_history import ensure_baseline, record_change
        if not entry.created_target:
            ensure_baseline(db, target)
        record_change(db, target)
    db.add(AuditEntry(
        user_id=user.id, kind=AUDIT_KIND_UNDO, tool=entry.tool, target_kind=entry.target_kind,
        target_id=entry.target_id, target_label=getattr(target, spec.label_field),
        changes=json.dumps(restore), undoes_id=entry.id,
    ))
    entry.undone_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        # e.g. undoing a budget's removal after a new one took its category.
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Can't undo: it has changed since.") from None
    db.refresh(entry)
    return entry


def claude_markers(db: Session, user_id: uuid.UUID, target_kind: str, target_ids) -> dict:
    """{target id: {audit_id, at}}: Claude's latest change to each item that
    is still in effect (a write made through an MCP grant, not undone)."""
    ids = list(target_ids)
    if not ids:
        return {}
    rows = (
        db.query(AuditEntry.target_id, AuditEntry.id, AuditEntry.created_at)
        .filter(
            AuditEntry.user_id == user_id, AuditEntry.kind == AUDIT_KIND_WRITE,
            AuditEntry.target_kind == target_kind, AuditEntry.target_id.in_(ids),
            AuditEntry.client_id.is_not(None), AuditEntry.undone_at.is_(None),
        )
        .order_by(AuditEntry.created_at)
        .all()
    )
    return {target_id: {"audit_id": audit_id, "at": at} for target_id, audit_id, at in rows}


def key_in_use(db: Session, user_id: uuid.UUID, key: str) -> bool:
    """Whether this idempotency key already has a live (unexpired) record:
    the request is a retry, and run_write will replay its first result."""
    cutoff = datetime.now(timezone.utc) - IDEMPOTENCY_TTL
    record = (
        db.query(WriteIdempotency.created_at)
        .filter(WriteIdempotency.user_id == user_id, WriteIdempotency.key == key)
        .first()
    )
    if record is None:
        return False
    created = record.created_at if record.created_at.tzinfo else record.created_at.replace(tzinfo=timezone.utc)
    return created >= cutoff
