"""Claude can't raise savable or safe-to-spend on its own (T-08-20, owner
decision D4 = strict parity; T-08-21b, owner decision D5 = yes).

One rule: no Claude change may make the money figures look better until the
user keeps it. For an **income** that is anything that brings in more
(below). For an **expense** commitment it is anything that takes out less:
a lower amount, a dismissal, a later next date, or another cadence
(T-08-21b, `keep_kind` "expense_cut"). Incomes count the *lower* of now and
before-Claude, expenses the *higher*. Raising or confirming a bill lowers
the figures, so it applies at once.

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

A dismissal brings nothing in, so it waits for keep only when it could bring
payday nearer (T-08-21): see `applied_dismissals`. Any other Claude dismissal
applies at once, like a kept change.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models import AuditEntry, CommitmentDirection, CommitmentRule, CommitmentStatus, PlannedItem
from app.models.audit import AUDIT_KIND_WRITE
from app.services.planning_writes import TARGETS

# The fields that decide how much an income brings in, and when.
MONEY_FIELDS = ("amount", "cadence", "interval_days", "interval_months", "next_date", "status")
# The card link decides whether a bill and its card's repayment count once or
# both (T-08-8), so a link Claude sets is held like a cut (sec on T-08-21b).
HELD_FIELDS = MONEY_FIELDS + ("card_account_id", "card_link_source")
PENDING, KEPT = "pending", "kept"
INCOME_KIND, EXPENSE_CUT_KIND = "income", "expense_cut"


def keep_kind(rule: CommitmentRule) -> str:
    """What a held change to this commitment holds back (ux spec 9, A8a)."""
    return INCOME_KIND if rule.direction == CommitmentDirection.INCOME.value else EXPENSE_CUT_KIND


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


def _is_dismissal(entry: AuditEntry) -> bool:
    confirmed = CommitmentStatus.CONFIRMED.value
    return any(
        c["field"] == "status" and c["before"] == confirmed and c["after"] != confirmed
        for c in json.loads(entry.changes)
    )


def _favourable(entry: AuditEntry, direction: str) -> list[dict]:
    """The money changes in a write that need the user to keep them: those
    that could make the figures look better. For an income: more coming in,
    or payday moved nearer (a dismissal that isn't in `applied`, T-08-21).
    For an expense: less going out (T-08-21b)."""
    income = direction == CommitmentDirection.INCOME.value
    confirmed = CommitmentStatus.CONFIRMED.value
    out = []
    for c in json.loads(entry.changes):
        field = c["field"]
        if field not in HELD_FIELDS:
            continue
        if field == "amount":
            after, before = Decimal(c["after"] or 0), Decimal(c["before"] or 0)
            if (after > before) if income else (after < before):
                out.append(c)
        elif field == "status":
            # Confirming brings an income in; dismissing one can make a
            # nearer income payday (T-08-21). Dismissing a bill takes it out.
            started, stopped = (
                c["after"] == confirmed and c["before"] != confirmed,
                c["before"] == confirmed and c["after"] != confirmed,
            )
            if (started or stopped) if income else stopped:
                out.append(c)
        elif field in ("card_account_id", "card_link_source"):
            # Linking a bill to a card (or moving it to another card) can
            # count it once with the card's repayment instead of both;
            # clearing a link only adds. card_link_source is never held on
            # its own: it is tracked so a revert or hand edit covers it with
            # card_account_id.
            if field == "card_account_id" and not income and c["after"] is not None:
                out.append(c)
        elif field == "next_date" and not income:
            # A bill moved later can leave the window; moved earlier, it can't.
            if c["after"] is None or c["before"] is None or c["after"] > c["before"]:
                out.append(c)
        else:  # how often (or, for an income, when): could move money across a window
            out.append(c)
    return out


def _settled(row: AuditEntry, applied: frozenset) -> bool:
    """Kept, or a dismissal that applies at once: its values stand."""
    return row.kept_at is not None or row.id in applied


def _live_fields(rows: list[AuditEntry], applied: frozenset = frozenset()) -> dict[uuid.UUID, set[str]]:
    """{row id: the money fields of that Claude write still in effect}.

    Walking newest first, a field stops being Claude's once the user set it
    by hand afterwards, or a newer Claude change to it was kept (the user
    accepted that value instead), or a newer dismissal applied at once. A
    newer *pending* change doesn't settle an older one: both revert, newest
    first."""
    settled: set[str] = set()
    out = {}
    for row in reversed(rows):
        fields = {c["field"] for c in json.loads(row.changes) if c["field"] in HELD_FIELDS}
        user_set = set(row.user_set_fields or [])
        out[row.id] = fields - user_set - settled
        settled |= user_set
        if _settled(row, applied):
            settled |= fields
    return out


def keep_states(rule: CommitmentRule | None, rows: list[AuditEntry],
                applied: frozenset = frozenset()) -> dict[uuid.UUID, str | None]:
    """{row id: `pending`, `kept`, or None (D4 doesn't apply)} for Claude's
    not-undone writes to one income commitment, oldest first. `applied`:
    from `applied_dismissals`."""
    live = _live_fields(rows, applied)
    out = {}
    for row in rows:
        out[row.id] = None
        if rule is None or row.client_id is None or row.id in applied:
            continue
        raising = _favourable(row, rule.direction)
        if not raising:
            continue
        if row.kept_at is not None:
            out[row.id] = KEPT
        elif any(c["field"] in live[row.id] for c in raising):
            out[row.id] = PENDING
    return out


def pending_ids(rule: CommitmentRule, rows: list[AuditEntry], applied: frozenset = frozenset()) -> list[uuid.UUID]:
    """Claude's writes to this commitment that are waiting to be kept, oldest first."""
    by_id = keep_states(rule, rows, applied)
    return [r.id for r in rows if by_id[r.id] == PENDING]


def commitment_keep(rule: CommitmentRule, rows: list[AuditEntry],
                    applied: frozenset = frozenset()) -> tuple[str | None, object]:
    """(keep, kept_at) for a commitment: pending if any of Claude's writes is."""
    by_id = keep_states(rule, rows, applied)
    states = [(by_id[r.id], r.kept_at) for r in rows]
    if any(s == PENDING for s, _ in states):
        return PENDING, None
    kept = [at for s, at in states if s == KEPT]
    return (KEPT, max(kept)) if kept else (None, None)


def held_back(rule: CommitmentRule, rows: list[AuditEntry], value) -> object | None:
    """The version of a commitment to count while Claude's changes to it are
    pending, judged by `value(version)` (the money it moves in some window).
    An income counts the lower of now and before-Claude; an expense the safe
    side of each part on its own (`_expense_held`). None if that is "not a
    confirmed commitment" (it counts nothing)."""
    before = before_claude(rule, rows)
    if rule.direction != CommitmentDirection.INCOME.value:
        return _expense_held(rule, before, value)
    confirmed = CommitmentStatus.CONFIRMED.value
    now_worth = value(rule) if rule.status == confirmed else Decimal(0)
    before_worth = value(before) if before.status == confirmed else Decimal(0)
    if now_worth <= before_worth:
        return rule if rule.status == confirmed else None
    if before.status != confirmed:
        return None
    return _version(rule, before)


TIMING_FIELDS = ("next_date", "cadence", "interval_days", "interval_months")


def _expense_held(rule: CommitmentRule, before, value) -> object | None:
    """A bill counted the safe way, part by part (sec on #131): a version-by-
    version choice let a 1p raise carry a new card link through.

    - status: counted if confirmed now or before Claude;
    - amount: the higher;
    - when and how often: whichever of the two schedules moves more money;
    - card link: none if it has none now (both then count), else the link
      from before Claude while Claude's link is pending."""
    confirmed = CommitmentStatus.CONFIRMED.value
    if confirmed not in (rule.status, before.status):
        return None
    if all(getattr(before, f) == getattr(rule, f) for f in HELD_FIELDS):
        return rule
    amount = max(rule.amount, before.amount)
    timing = max(
        (before, rule),
        key=lambda v: value(SimpleNamespace(amount=amount, **{f: getattr(v, f) for f in TIMING_FIELDS})),
    )
    link = rule if rule.card_account_id is None else before
    return SimpleNamespace(
        id=rule.id, direction=rule.direction, label=rule.label, account_id=rule.account_id,
        status=confirmed, amount=amount,
        **{f: getattr(timing, f) for f in TIMING_FIELDS},
        card_account_id=link.card_account_id, card_link_source=link.card_link_source,
    )


def _version(rule: CommitmentRule, view) -> SimpleNamespace:
    return SimpleNamespace(
        id=rule.id, direction=rule.direction, label=rule.label, account_id=rule.account_id,
        **{f: getattr(view, f) for f in HELD_FIELDS},
    )


def counted_commitments(db: Session, user_id: uuid.UUID, direction: str, value) -> list:
    """The commitments of one direction to count in a figure judged by
    `value`, with Claude's pending changes resolved the safe way
    (`held_back`). Every status is read: a dismissal may be Claude's."""
    rules = (
        db.query(CommitmentRule)
        .filter(CommitmentRule.user_id == user_id, CommitmentRule.direction == direction)
        .all()
    )
    claude = claude_rows(db, user_id, [r.id for r in rules])
    confirmed = CommitmentStatus.CONFIRMED.value
    out = []
    for r in rules:
        version = held_back(r, claude[r.id], value) if r.id in claude else (r if r.status == confirmed else None)
        if version is not None:
            out.append(version)
    return out


def held_values(rule: CommitmentRule, rows: list[AuditEntry], applied: frozenset = frozenset()) -> dict:
    """{"held_amount", "held_next_date"}: the before-Claude value the figures
    still use, for each that a pending change moved (else None; ux KP18)."""
    before = before_claude(rule, rows, applied)
    income = rule.direction == CommitmentDirection.INCOME.value
    amount_held = before.amount < rule.amount if income else before.amount > rule.amount
    date_held = before.next_date != rule.next_date if income else before.next_date < rule.next_date
    return {
        "held_amount": before.amount if amount_held else None,
        "held_next_date": before.next_date if date_held else None,
    }


def pre_claude_payday_incomes(db: Session, user) -> list:
    """The income rules that defined payday before Claude's pending changes
    (T-08-21): every income commitment (dismissed ones too, a dismissal may
    be Claude's) seen through `before_claude`, kept if it was confirmed then,
    with the is_payday preference applied as `_payday_incomes` does."""
    rules = _income_rules(db, user.id)
    claude = claude_rows(db, user.id, [r.id for r in rules])
    applied = _applied_dismissals(rules, claude)
    out = []
    for r in rules:
        view = before_claude(r, claude[r.id], applied) if r.id in claude else r
        if view.status == CommitmentStatus.CONFIRMED.value:
            out.append(SimpleNamespace(is_payday=r.is_payday, **{f: getattr(view, f) for f in MONEY_FIELDS}))
    flagged = [r for r in out if r.is_payday]
    return flagged or out


def _income_rules(db: Session, user_id: uuid.UUID) -> list[CommitmentRule]:
    return (
        db.query(CommitmentRule)
        .filter(CommitmentRule.user_id == user_id, CommitmentRule.direction == CommitmentDirection.INCOME.value)
        .all()
    )


def applied_dismissals(db: Session, user_id: uuid.UUID) -> frozenset:
    """The audit ids of Claude's income dismissals that apply at once."""
    rules = _income_rules(db, user_id)
    return _applied_dismissals(rules, claude_rows(db, user_id, [r.id for r in rules]))


def _applied_dismissals(rules: list[CommitmentRule], claude: dict) -> frozenset:
    """Claude's pending income dismissals that can't bring payday nearer, so
    apply at once (T-08-21 follow-up).

    Payday is the soonest date among the payday incomes: the flagged ones,
    or every income if none is flagged, or 30 days out if there are none.
    Taking incomes out of that set can only make its soonest date the same
    or later. Payday can come nearer only when the dismissals change *which*
    set it is: the flagged ones all go (payday falls back to every income)
    or every income goes (the 30-day fallback). Then the dismissals of
    payday incomes are held; otherwise every dismissal applies at once.

    It reads the incomes as they are now, so it can change after the
    dismissal: flagging another payday releases a held one, and the user's
    own changes (dismissing their last other income, say) can hold an
    applied one again. Both are the safe side for the window."""
    dismissals: dict[uuid.UUID, list[uuid.UUID]] = {}
    for r in rules:
        rows = claude.get(r.id, [])
        live = _live_fields(rows)
        for row in rows:
            if row.kept_at is None and _is_dismissal(row) and "status" in live[row.id]:
                dismissals.setdefault(r.id, []).append(row.id)
    if not dismissals:
        return frozenset()
    confirmed = CommitmentStatus.CONFIRMED.value
    before = [r for r in rules if (before_claude(r, claude[r.id]) if r.id in claude else r).status == confirmed]

    def payday_set(incomes) -> set:
        return {r.id for r in incomes if r.is_payday} or {r.id for r in incomes}

    all_set = payday_set(before)
    rest_set = payday_set([r for r in before if r.id not in dismissals])
    held = set(dismissals) & all_set if not rest_set or not rest_set <= all_set else set()
    return frozenset(row_id for rid, ids in dismissals.items() if rid not in held for row_id in ids)


def before_claude(rule: CommitmentRule, rows: list[AuditEntry], applied: frozenset = frozenset()) -> SimpleNamespace:
    """The commitment's money fields as they were before Claude's pending
    (not kept) writes, walking newest first and reverting each field that is
    still Claude's (`_live_fields`)."""
    live = _live_fields(rows, applied)
    view = SimpleNamespace(**{f: getattr(rule, f) for f in HELD_FIELDS})
    for entry in reversed(rows):
        if _settled(entry, applied):
            continue
        for c in json.loads(entry.changes):
            if c["field"] in live[entry.id]:
                setattr(view, c["field"], _value(c["field"], c["before"]))
    return view


def planned_removal_states(db: Session, user_id: uuid.UUID,
                           pending_only: bool = False) -> dict[uuid.UUID, tuple[str, PlannedItem]]:
    """{audit id: (`pending` | `kept`, item)} for Claude's not-undone removals
    of a planned *expense* (T-08-21b part 2, sec). Removing one would raise
    safe-to-spend, so it keeps counting until kept. Planned income never
    counts (D1), so removing it holds nothing."""
    rows = (
        db.query(AuditEntry)
        .filter(
            AuditEntry.user_id == user_id, AuditEntry.kind == AUDIT_KIND_WRITE,
            AuditEntry.target_kind == "planned_event", AuditEntry.tool == "remove_planned_event",
            AuditEntry.client_id.is_not(None), AuditEntry.undone_at.is_(None),
            *([AuditEntry.kept_at.is_(None)] if pending_only else []),
        )
        .all()
    )
    if not rows:
        return {}
    items = {
        i.id: i for i in db.query(PlannedItem).filter(
            PlannedItem.user_id == user_id, PlannedItem.id.in_({r.target_id for r in rows}),
        )
    }
    out = {}
    for row in rows:
        item = items.get(row.target_id)
        if item is None or item.direction != CommitmentDirection.EXPENSE.value:
            continue
        if item.deleted_at is not None:
            continue  # the user deleted it on the web: nothing is held (T-12-9b)
        if row.kept_at is not None:
            out[row.id] = (KEPT, item)
        elif not item.active:
            out[row.id] = (PENDING, item)
    return out


def held_removed_planned(db: Session, user_id: uuid.UUID) -> list[PlannedItem]:
    """Planned expenses Claude removed that still count until kept."""
    return [item for state, item in planned_removal_states(db, user_id, pending_only=True).values() if state == PENDING]


def record_user_edit(db: Session, user_id: uuid.UUID, commitment_id: uuid.UUID, fields) -> None:
    """A web edit set these fields by hand: from now on they are the user's,
    not Claude's, on every pending Claude change to this commitment. Not
    keeping (Q-D4): the other fields stay pending. Caller commits."""
    touched = set(fields) & set(HELD_FIELDS)
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
