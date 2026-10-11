"""Claude can't raise savable on its own (T-08-20, owner decision D4 = strict parity).

An income commitment that Claude changed so it brings in more (raised the
amount, confirmed it from suggested, changed when or how often it arrives)
counts in `savable` only as it was before Claude, until the user keeps the
change in the app (POST /audit/{id}/keep, web session only). Taken from the
audit trail: Claude's writes are the rows made through an MCP grant
(`client_id` set) that are not undone; keeping stamps `kept_at`.

A hand edit is not keeping (owner, Q-D4). But a field the user has since set
by hand in the app is the user's value, not Claude's (ux KP14). That is
*recorded*: the web edit stamps the field on Claude's pending rows
(`user_set_fields`). It is never inferred from the stored value, because
sync rolls a past next_date forward on its own (sec on #121).

Savable counts the *smaller* of the commitment as it is and as it was before
Claude's pending changes, so a change that brings in less counts at once.
Safe-to-spend never counts income, and the forecast may show the new figure
(owner decision D1 = a).
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models import AuditEntry, CommitmentDirection, CommitmentRule, CommitmentStatus
from app.models.audit import AUDIT_KIND_WRITE
from app.services.planning_writes import TARGETS

# The fields that decide how much an income brings in, and when.
MONEY_FIELDS = ("amount", "cadence", "interval_days", "interval_months", "next_date", "status")
PENDING, KEPT = "pending", "kept"


def claude_rows(db: Session, user_id: uuid.UUID, commitment_ids) -> dict[uuid.UUID, list[AuditEntry]]:
    """{commitment id: Claude's not-undone writes to it, oldest first}."""
    ids = list(commitment_ids)
    if not ids:
        return {}
    rows = (
        db.query(AuditEntry)
        .filter(
            AuditEntry.user_id == user_id, AuditEntry.kind == AUDIT_KIND_WRITE,
            AuditEntry.target_kind == "commitment", AuditEntry.target_id.in_(ids),
            AuditEntry.client_id.is_not(None), AuditEntry.undone_at.is_(None),
        )
        .order_by(AuditEntry.created_at)
        .all()
    )
    out: dict = {}
    for row in rows:
        out.setdefault(row.target_id, []).append(row)
    return out


def _value(field: str, raw):
    return None if raw is None else TARGETS["commitment"].fields[field](raw)


def _raising(entry: AuditEntry) -> list[dict]:
    """The money changes in a write that could bring in more."""
    out = []
    for c in json.loads(entry.changes):
        field = c["field"]
        if field not in MONEY_FIELDS:
            continue
        if field == "amount":
            if Decimal(c["after"] or 0) > Decimal(c["before"] or 0):
                out.append(c)
        elif field == "status":
            if c["after"] == CommitmentStatus.CONFIRMED.value and c["before"] != CommitmentStatus.CONFIRMED.value:
                out.append(c)
        else:  # when or how often it arrives: could bring more into the window
            out.append(c)
    return out


def _live_fields(rows: list[AuditEntry]) -> dict[uuid.UUID, set[str]]:
    """{row id: the money fields of that Claude write still in effect}.

    Walking newest first, a field stops being Claude's once the user set it
    by hand afterwards, or a newer Claude change to it was kept (the user
    accepted that value instead). A newer *pending* change doesn't settle an
    older one: both revert, newest first."""
    settled: set[str] = set()
    out = {}
    for row in reversed(rows):
        fields = {c["field"] for c in json.loads(row.changes) if c["field"] in MONEY_FIELDS}
        user_set = set(row.user_set_fields or [])
        out[row.id] = fields - user_set - settled
        settled |= user_set
        if row.kept_at is not None:
            settled |= fields
    return out


def keep_states(rule: CommitmentRule | None, rows: list[AuditEntry]) -> dict[uuid.UUID, str | None]:
    """{row id: `pending`, `kept`, or None (D4 doesn't apply)} for Claude's
    not-undone writes to one income commitment, oldest first."""
    live = _live_fields(rows)
    out = {}
    for row in rows:
        out[row.id] = None
        if rule is None or rule.direction != CommitmentDirection.INCOME.value or row.client_id is None:
            continue
        raising = _raising(row)
        if not raising:
            continue
        if row.kept_at is not None:
            out[row.id] = KEPT
        elif any(c["field"] in live[row.id] for c in raising):
            out[row.id] = PENDING
    return out


def commitment_keep(rule: CommitmentRule, rows: list[AuditEntry]) -> tuple[str | None, object]:
    """(keep, kept_at) for a commitment: pending if any of Claude's writes is."""
    by_id = keep_states(rule, rows)
    states = [(by_id[r.id], r.kept_at) for r in rows]
    if any(s == PENDING for s, _ in states):
        return PENDING, None
    kept = [at for s, at in states if s == KEPT]
    return (KEPT, max(kept)) if kept else (None, None)


def held_back(rule: CommitmentRule, rows: list[AuditEntry], value) -> object | None:
    """The version of an income to count while Claude's changes to it are
    pending: whichever of now and before-Claude `value(version)` rates lower,
    or None if that is "not a confirmed commitment" (it counts nothing)."""
    before = before_claude(rule, rows)
    confirmed = CommitmentStatus.CONFIRMED.value
    now_worth = value(rule) if rule.status == confirmed else Decimal(0)
    before_worth = value(before) if before.status == confirmed else Decimal(0)
    if before_worth >= now_worth:
        return rule if rule.status == confirmed else None
    if before.status != confirmed:
        return None
    return SimpleNamespace(
        id=rule.id, direction=rule.direction, label=rule.label, account_id=rule.account_id,
        **{f: getattr(before, f) for f in MONEY_FIELDS},
    )


def before_claude(rule: CommitmentRule, rows: list[AuditEntry]) -> SimpleNamespace:
    """The commitment's money fields as they were before Claude's pending
    (not kept) writes, walking newest first and reverting each field that is
    still Claude's (`_live_fields`)."""
    live = _live_fields(rows)
    view = SimpleNamespace(**{f: getattr(rule, f) for f in MONEY_FIELDS})
    for entry in reversed(rows):
        if entry.kept_at is not None:
            continue
        for c in json.loads(entry.changes):
            if c["field"] in live[entry.id]:
                setattr(view, c["field"], _value(c["field"], c["before"]))
    return view


def record_user_edit(db: Session, user_id: uuid.UUID, commitment_id: uuid.UUID, fields) -> None:
    """A web edit set these fields by hand: from now on they are the user's,
    not Claude's, on every pending Claude change to this commitment. Not
    keeping (Q-D4): the other fields stay pending. Caller commits."""
    touched = set(fields) & set(MONEY_FIELDS)
    if not touched:
        return
    rows = (
        db.query(AuditEntry)
        .filter(
            AuditEntry.user_id == user_id, AuditEntry.kind == AUDIT_KIND_WRITE,
            AuditEntry.target_kind == "commitment", AuditEntry.target_id == commitment_id,
            AuditEntry.client_id.is_not(None), AuditEntry.undone_at.is_(None), AuditEntry.kept_at.is_(None),
        )
        .all()
    )
    for row in rows:
        row.user_set_fields = sorted(set(row.user_set_fields or []) | touched)
