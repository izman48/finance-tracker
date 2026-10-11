"""Claude can't raise safe-to-spend or savable on its own (T-08-20 D4, T-08-21b).

One rule: no Claude change may make the money figures look better until the
user keeps it. For an **income** that means anything that brings in more
(below); for an **expense** commitment, anything that takes out less: a lower
amount, a dismissal, a later date or another cadence (T-08-21b). Expenses
count the *higher* of now and before-Claude, incomes the *lower*.

An income commitment that Claude changed so it brings in more (raised the
amount, confirmed it from suggested, changed when or how often it arrives)
counts in `savable` only as it was before Claude, until the user keeps the
change in the app (POST /audit/{id}/keep, web session only). Taken from the
audit trail: Claude's writes are the rows made through an MCP grant
(`client_id` set) that are not undone; keeping stamps `kept_at`.

A hand edit is not keeping (owner, Q-D4). But a field the user has since set
by hand is the user's value, not Claude's: a change is only "in effect" for
a field while the commitment still holds the value Claude wrote (ux KP14).

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


def _favourable(entry: AuditEntry, direction: str) -> list[dict]:
    """The money changes in a write that could make the figures look better:
    more coming in for an income, less going out for an expense."""
    income = direction == CommitmentDirection.INCOME.value
    confirmed = CommitmentStatus.CONFIRMED.value
    out = []
    for c in json.loads(entry.changes):
        field = c["field"]
        if field not in MONEY_FIELDS:
            continue
        if field == "amount":
            after, before = Decimal(c["after"] or 0), Decimal(c["before"] or 0)
            if (after > before) if income else (after < before):
                out.append(c)
        elif field == "status":
            started = c["after"] == confirmed and c["before"] != confirmed
            stopped = c["before"] == confirmed and c["after"] != confirmed
            if started if income else stopped:
                out.append(c)
        else:  # when or how often: could move money into or out of a window
            out.append(c)
    return out


def keep_state(rule: CommitmentRule, entry: AuditEntry) -> str | None:
    """`pending`, `kept`, or None when the rule doesn't apply to this write."""
    if rule is None or entry.client_id is None or entry.undone_at is not None:
        return None
    raising = _favourable(entry, rule.direction)
    if not raising:
        return None
    if entry.kept_at is not None:
        return KEPT
    in_effect = any(getattr(rule, c["field"]) == _value(c["field"], c["after"]) for c in raising)
    return PENDING if in_effect else None


def commitment_keep(rule: CommitmentRule, rows: list[AuditEntry]) -> tuple[str | None, object]:
    """(keep, kept_at) for a commitment: pending if any of Claude's writes is."""
    states = [(keep_state(rule, r), r.kept_at) for r in rows]
    if any(s == PENDING for s, _ in states):
        return PENDING, None
    kept = [at for s, at in states if s == KEPT]
    return (KEPT, max(kept)) if kept else (None, None)


def held_back(rule: CommitmentRule, rows: list[AuditEntry], value) -> object | None:
    """The version of a commitment to count while Claude's changes to it are
    pending, judged by `value(version)` (the money it moves in some window):
    the lower of now and before-Claude for an income, the higher for an
    expense. None if the chosen version isn't a confirmed commitment (it
    counts nothing)."""
    before = before_claude(rule, rows)
    confirmed = CommitmentStatus.CONFIRMED.value
    now_worth = value(rule) if rule.status == confirmed else Decimal(0)
    before_worth = value(before) if before.status == confirmed else Decimal(0)
    income = rule.direction == CommitmentDirection.INCOME.value
    use_now = now_worth <= before_worth if income else now_worth >= before_worth
    if use_now:
        return rule if rule.status == confirmed else None
    if before.status != confirmed:
        return None
    return SimpleNamespace(
        id=rule.id, direction=rule.direction, label=rule.label, account_id=rule.account_id,
        card_account_id=rule.card_account_id, card_link_source=rule.card_link_source,
        **{f: getattr(before, f) for f in MONEY_FIELDS},
    )


def counted_commitments(db: Session, user_id: uuid.UUID, direction: str, value) -> list:
    """The commitments of one direction to count, with Claude's pending
    changes resolved the safe way (`held_back`). Looks at every status, since
    a dismissal may be Claude's."""
    rules = (
        db.query(CommitmentRule)
        .filter(CommitmentRule.user_id == user_id, CommitmentRule.direction == direction)
        .all()
    )
    claude = claude_rows(db, user_id, [r.id for r in rules])
    out = []
    for r in rules:
        if r.id in claude:
            version = held_back(r, claude[r.id], value)
        else:
            version = r if r.status == CommitmentStatus.CONFIRMED.value else None
        if version is not None:
            out.append(version)
    return out


def pre_claude_payday_incomes(db: Session, user) -> list:
    """The income rules that defined payday before Claude's pending changes
    (T-08-21): every income commitment (dismissed ones too, a dismissal may
    be Claude's) seen through `before_claude`, kept if it was confirmed then,
    with the is_payday preference applied as `_payday_incomes` does."""
    rules = (
        db.query(CommitmentRule)
        .filter(CommitmentRule.user_id == user.id, CommitmentRule.direction == CommitmentDirection.INCOME.value)
        .all()
    )
    claude = claude_rows(db, user.id, [r.id for r in rules])
    confirmed = CommitmentStatus.CONFIRMED.value
    out = []
    for r in rules:
        view = before_claude(r, claude[r.id]) if r.id in claude else r
        if view.status == confirmed:
            out.append(SimpleNamespace(is_payday=r.is_payday, **{f: getattr(view, f) for f in MONEY_FIELDS}))
    flagged = [r for r in out if r.is_payday]
    return flagged or out


def before_claude(rule: CommitmentRule, rows: list[AuditEntry]) -> SimpleNamespace:
    """The commitment's money fields as they were before Claude's pending
    (not kept) writes, walking newest first and reverting a field only while
    it still holds the value that write set."""
    view = SimpleNamespace(**{f: getattr(rule, f) for f in MONEY_FIELDS})
    for entry in reversed(rows):
        if entry.kept_at is not None:
            continue
        for c in json.loads(entry.changes):
            field = c["field"]
            if field in MONEY_FIELDS and getattr(view, field) == _value(field, c["after"]):
                setattr(view, field, _value(field, c["before"]))
    return view
