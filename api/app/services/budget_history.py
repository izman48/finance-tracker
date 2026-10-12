"""Budget history: the change log, lazy per-cycle snapshots, and
GET /budgets/history (T-09-3; budgets concept section 14, BH1-BH12; sec's
T-09-3 criteria).

- Every change to a budget appends a `budget_changes` row with its full
  state (limit, paused, active) from that moment, so a closed cycle is judged
  by the limit in force at its close, never today's.
- A closed cycle's snapshot is written once, the first time it is loaded,
  with the user's key (spend is in encrypted transactions). It stores the
  cycle's own dates, so a later payday change never moves history, and a
  unique (budget, cycle start) makes two loads at once write one row.
  Snapshots are never updated.
- "Kept" is computed here, once: spend at or under the limit at close.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Budget, BudgetChange, BudgetCycleSnapshot
from app.services.analytics.common import _today
from app.services.budget_spend import budget_spend
from app.services.budgets import current_cycle, previous_cycles

HISTORY_MAX_CYCLES = 12
# Cycles looked back over when writing missing snapshots.
SNAPSHOT_LOOKBACK = HISTORY_MAX_CYCLES
TREND_MIN_CYCLES = 6
TREND_SAME_POUNDS = Decimal(10)
TREND_SAME_SHARE = Decimal("0.02")


def record_change(db: Session, budget: Budget, at: datetime | None = None) -> None:
    """Append the budget's state from now on. Call with every write to a
    budget (create, limit, pause, resume, remove), before the commit."""
    db.flush()  # a new budget needs its id
    db.add(BudgetChange(
        user_id=budget.user_id, budget_id=budget.id, effective_at=at or datetime.now(timezone.utc),
        limit_pounds=Decimal(budget.limit_pounds), paused=bool(budget.paused), active=bool(budget.active),
    ))


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _changes(db: Session, user, budget: Budget) -> list[BudgetChange]:
    """The budget's change log, oldest first. A budget made before the log
    existed gets a first row now, effective from its creation, with its
    current state (an encrypted limit can't be read by a migration)."""
    rows = (
        db.query(BudgetChange)
        .filter(BudgetChange.user_id == user.id, BudgetChange.budget_id == budget.id)
        .order_by(BudgetChange.effective_at, BudgetChange.id)
        .all()
    )
    if not rows:
        record_change(db, budget, at=_aware(budget.created_at) if budget.created_at else None)
        db.commit()
        return _changes(db, user, budget)
    return rows


def _state_at_close(changes: list[BudgetChange], cycle_end: date) -> BudgetChange | None:
    close = datetime.combine(cycle_end, time.max, tzinfo=timezone.utc)
    in_force = [c for c in changes if _aware(c.effective_at) <= close]
    return in_force[-1] if in_force else None


def write_snapshots(db: Session, user) -> None:
    """Write the snapshots of closed cycles not yet written, for every budget
    that existed and was active at the cycle's close. Cycles start after the
    last stored one, so a payday change never overlaps stored history."""
    today = _today()
    cycle = current_cycle(db, user, today)
    if cycle.fallback:
        return  # no payday: no cycles to close
    stored = db.query(BudgetCycleSnapshot.cycle_end).filter(BudgetCycleSnapshot.user_id == user.id)
    last_end = max((end for (end,) in stored), default=None)
    closed = [c for c in previous_cycles(db, user, cycle, SNAPSHOT_LOOKBACK) if last_end is None or c.start > last_end]
    if not closed:
        return
    budgets = db.query(Budget).filter(Budget.user_id == user.id).all()
    logs = {b.id: _changes(db, user, b) for b in budgets}
    for c in closed:
        states = {b.id: _state_at_close(logs[b.id], c.end) for b in budgets}
        live = [b for b in budgets if states[b.id] is not None and states[b.id].active]
        if not live:
            continue
        spend = budget_spend(db, user, c.start, c.end).by_category
        for b in live:
            state = states[b.id]
            db.add(BudgetCycleSnapshot(
                user_id=user.id, budget_id=b.id, cycle_start=c.start, cycle_end=c.end,
                limit_pounds=Decimal(state.limit_pounds), spent=spend.get(b.category, Decimal(0)),
                paused=state.paused,
            ))
            try:
                db.commit()
            except IntegrityError:  # another worker wrote it first
                db.rollback()


def history(db: Session, user, cycles: int, before: date | None) -> dict:
    """GET /budgets/history: up to `cycles` completed cycles ending before
    `before` (newest first in storage, oldest first in the response)."""
    write_snapshots(db, user)
    categories = {b.id: b.category for b in db.query(Budget).filter(Budget.user_id == user.id)}
    query = db.query(BudgetCycleSnapshot).filter(BudgetCycleSnapshot.user_id == user.id)
    if before is not None:
        query = query.filter(BudgetCycleSnapshot.cycle_end < before)
    snaps = query.all()
    ranges = sorted({(s.cycle_start, s.cycle_end) for s in snaps}, reverse=True)
    shown, has_more = ranges[:cycles], len(ranges) > cycles
    shown = list(reversed(shown))  # oldest first
    by_range = {r: [s for s in snaps if (s.cycle_start, s.cycle_end) == r] for r in shown}

    overall = []
    for start, end in shown:
        counted = [s for s in by_range[(start, end)] if not s.paused]
        limit = sum((Decimal(s.limit_pounds) for s in counted), Decimal(0))
        spent = sum((Decimal(s.spent) for s in counted), Decimal(0))
        overall.append({
            "start": start, "end": end, "total_limit": limit, "total_spent": spent,
            "on_target": (spent <= limit) if counted else None,
        })

    per_budget = []
    for budget_id in sorted({s.budget_id for r in shown for s in by_range[r]}, key=lambda i: categories[i]):
        slots, kept, counted_spend = [], 0, []
        for start, end in shown:
            snap = next((s for s in by_range[(start, end)] if s.budget_id == budget_id), None)
            if snap is None:
                slots.append({"start": start, "end": end, "existed": False, "paused": False,
                              "limit_pounds": None, "spent": None, "kept": None})
                continue
            limit, spent = Decimal(snap.limit_pounds), Decimal(snap.spent)
            is_kept = None if snap.paused else spent <= limit
            if is_kept is not None:
                kept += is_kept
                counted_spend.append(spent)
            slots.append({"start": start, "end": end, "existed": True, "paused": snap.paused,
                          "limit_pounds": int(limit), "spent": spent, "kept": is_kept})
        per_budget.append({
            "budget_id": budget_id, "category": categories[budget_id],
            "kept": kept, "counted": len(counted_spend),
            "usually": (sum(counted_spend, Decimal(0)) / len(counted_spend)).quantize(Decimal("0.01"))
            if counted_spend else None,
            "cycles": slots,
        })

    return {
        "cycles": overall,
        "budgets": per_budget,
        "on_target": sum(1 for c in overall if c["on_target"]),
        "counted": sum(1 for c in overall if c["on_target"] is not None),
        "trend": _trend([c for c in overall if c["on_target"] is not None]),
        "has_more": has_more,
    }


def _trend(cycles: list[dict]) -> dict | None:
    """Mean budgeted spend of the latest 3 completed cycles against the 3
    before; "same" under £10 or 2%. None with fewer than 6 cycles."""
    if len(cycles) < TREND_MIN_CYCLES:
        return None
    latest = sum((c["total_spent"] for c in cycles[-3:]), Decimal(0)) / 3
    before = sum((c["total_spent"] for c in cycles[-6:-3]), Decimal(0)) / 3
    diff = (latest - before).quantize(Decimal("1"))
    same = abs(diff) < TREND_SAME_POUNDS or (before and abs(diff) < before * TREND_SAME_SHARE)
    return {"difference": abs(diff), "direction": "same" if same else ("lower" if diff < 0 else "higher")}
