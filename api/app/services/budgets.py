"""Budgets: cycles, validation, tracking and suggestions (T-09-2; budgets
concept sections 2, 13 and 15).

Spend always comes from `budget_spend` (T-09-1), the one counting rule.
Every query is scoped to the caller; categories are untrusted text and are
never logged. Nothing here changes a money figure: safe-to-spend is only
read, for the reconciliation line.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.display_text import has_hidden_characters
from app.models import Account, Budget, Transaction
from app.schemas.budgets import (
    BUDGETS_PER_USER_MAX,
    BudgetCycle,
    BudgetListResponse,
    BudgetResponse,
    BudgetSuggestion,
    BudgetSuggestResponse,
    CycleFigure,
    NotCounted,
    Reconciliation,
)
from app.services.analytics.commitments import last_payday, next_payday
from app.services.analytics.common import _today
from app.services.budget_spend import UNCATEGORISED, budget_spend

FALLBACK_DAYS = 30
SUGGEST_CYCLES = 3
SUGGEST_MAX = 8
COVERED_LOOKBACK_DAYS = 90
# Pace: within 10% of even spending is "on pace".
PACE_BAND = Decimal("0.10")


@dataclass(frozen=True)
class Cycle:
    start: date
    end: date
    fallback: bool


def current_cycle(db: Session, user, today: date) -> Cycle:
    """Last payday to the day before the next one. With no payday set, the
    last 30 days (the UI asks the user to set their payday)."""
    start = last_payday(db, user, today)
    if start is None:
        return Cycle(today - timedelta(days=FALLBACK_DAYS - 1), today, fallback=True)
    nxt = next_payday(db, user, today + timedelta(days=1))
    end = (nxt - timedelta(days=1)) if nxt else start + timedelta(days=FALLBACK_DAYS - 1)
    return Cycle(start, max(end, today), fallback=False)


def previous_cycles(db: Session, user, cycle: Cycle, n: int) -> list[Cycle]:
    """The n complete cycles before `cycle`, oldest first."""
    out: list[Cycle] = []
    start = cycle.start
    for _ in range(n):
        end = start - timedelta(days=1)
        prev = None if cycle.fallback else last_payday(db, user, end)
        start = prev if prev is not None and prev <= end else end - timedelta(days=FALLBACK_DAYS - 1)
        out.append(Cycle(start, end, cycle.fallback))
    return list(reversed(out))


def user_categories(db: Session, user) -> set[str]:
    """The categories on the user's own transactions (plain text column)."""
    rows = (
        db.query(Transaction.category)
        .join(Account)
        .filter(Account.user_id == user.id, Transaction.category.is_not(None))
        .distinct()
        .all()
    )
    return {c for (c,) in rows if c and c != UNCATEGORISED}


def commitment_covered(db: Session, user, today: date) -> set[str]:
    """Categories whose recent spending is mostly confirmed commitments
    (rent, bills): already in safe-to-spend, so not offered as budgets."""
    spend = budget_spend(db, user, today - timedelta(days=COVERED_LOOKBACK_DAYS), today)
    return {
        cat for cat, committed in spend.commitments_by_category.items()
        if committed > spend.by_category.get(cat, Decimal(0))
    }


def _refuse(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def validate_categories(db: Session, user, categories: list[str]) -> None:
    """Every category is one of the user's own, visible text, not mostly
    commitments, and listed once. Raises 422 with fixed words (the category
    itself is never echoed)."""
    if len(set(categories)) != len(categories):
        raise _refuse("Each category can appear only once.")
    if any(has_hidden_characters(c) or not c.strip() for c in categories):
        raise _refuse("That category isn't valid.")
    known = user_categories(db, user)
    if any(c not in known for c in categories):
        raise _refuse("Budgets can only use your existing categories.")
    covered = commitment_covered(db, user, _today())
    if any(c in covered for c in categories):
        raise _refuse("That category is mostly commitments, which are already counted in safe to spend.")


def active_budgets(db: Session, user) -> list[Budget]:
    return (
        db.query(Budget)
        .filter(Budget.user_id == user.id, Budget.active.is_(True))
        .order_by(Budget.created_at, Budget.id)
        .all()
    )


def owned_budget(db: Session, user, budget_id) -> Budget:
    """The caller's active budget, or 404 (another user's id included)."""
    budget = (
        db.query(Budget)
        .filter(Budget.id == budget_id, Budget.user_id == user.id, Budget.active.is_(True))
        .first()
    )
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return budget


def check_cap(count_after: int) -> None:
    if count_after > BUDGETS_PER_USER_MAX:
        raise _refuse(f"You can have at most {BUDGETS_PER_USER_MAX} budgets.")


# --- tracking ------------------------------------------------------------------------

def _status(spent: Decimal, pace: Decimal, limit: Decimal) -> str:
    if spent > limit:
        return "over"
    if spent > pace * (1 + PACE_BAND):
        return "ahead_of_pace"
    if spent < pace * (1 - PACE_BAND):
        return "under_pace"
    return "on_pace"


def budget_list(db: Session, user, markers: dict | None = None) -> BudgetListResponse:
    """GET /budgets: the current cycle, each budget's spend and pace, other
    spending, what's not counted, and the reconciliation line."""
    from app.services.analytics.summary import get_summary

    today = _today()
    cycle = current_cycle(db, user, today)
    spend = budget_spend(db, user, cycle.start, cycle.end)
    days_total = (cycle.end - cycle.start).days + 1
    elapsed = min(days_total, (today - cycle.start).days + 1)
    days_left = (cycle.end - today).days
    share = Decimal(elapsed) / Decimal(days_total)

    budgets = active_budgets(db, user)
    tracked = {b.category for b in budgets if not b.paused}
    rows = []
    budgets_left = Decimal(0)
    for b in budgets:
        limit = Decimal(b.limit_pounds)
        spent = spend.by_category.get(b.category, Decimal(0))
        pace = (limit * share).quantize(Decimal("0.01"))
        if not b.paused:
            budgets_left += max(Decimal(0), limit - spent)
        rows.append(BudgetResponse(
            id=b.id, category=b.category, limit_pounds=int(limit), paused=b.paused, created_via=b.created_via,
            spent=spent, pace_spent=pace, over_by=max(Decimal(0), spent - limit),
            status=None if b.paused else _status(spent, pace, limit),
            changed_by_claude=(markers or {}).get(b.id),
        ))
    other = sum((v for k, v in spend.by_category.items() if k not in tracked), Decimal(0))
    total = sum(spend.by_category.values(), Decimal(0))

    # No payday, no reconciliation (eng-a on #150): the 30-day fallback window
    # isn't the cycle safe-to-spend runs to.
    reconciliation = None
    if any(not b.paused for b in budgets) and not cycle.fallback:
        safe = Decimal(get_summary(db, user)["safe_to_spend"])
        other_at_pace = (other / Decimal(elapsed) * Decimal(max(days_left, 0))).quantize(Decimal("0.01"))
        reconciliation = Reconciliation(
            safe_to_spend=safe, budgets_left=budgets_left, other_at_pace=other_at_pace,
            headroom=safe - budgets_left - other_at_pace,
        )
    return BudgetListResponse(
        cycle=BudgetCycle(start=cycle.start, end=cycle.end, days_total=days_total, days_left=max(days_left, 0),
                          fallback=cycle.fallback),
        budgets=rows, other_spending=other, total_spent=total,
        not_counted=NotCounted(**spend.excluded), reconciliation=reconciliation,
    )


# --- suggest (dry) ---------------------------------------------------------------------

def _round_up_10(amount: Decimal) -> int:
    return max(10, int(math.ceil(amount / 10)) * 10)


def _first_transaction_date(db: Session, user) -> date | None:
    first = (
        db.query(func.min(Transaction.transaction_date))
        .join(Account)
        .filter(Account.user_id == user.id)
        .scalar()
    )
    if first is None:
        return None
    return first.date() if isinstance(first, datetime) else first


def suggest(db: Session, user) -> BudgetSuggestResponse:
    """The median of the last 3 complete cycles per category, rounded up to
    £10, or "not_enough_history". Reads only."""
    today = _today()
    cycle = current_cycle(db, user, today)
    cycles = previous_cycles(db, user, cycle, SUGGEST_CYCLES)
    spends = [budget_spend(db, user, c.start, c.end) for c in cycles]
    this_cycle = budget_spend(db, user, cycle.start, today)
    covered = commitment_covered(db, user, today)
    # Enough history: the user's transactions reach back to the start of the
    # oldest of the three cycles, so none of them is partly missing data
    # (eng-a on #150: a partial cycle would pull the median down).
    first = _first_transaction_date(db, user)
    enough = first is not None and first <= cycles[0].start
    current = {b.category: int(Decimal(b.limit_pounds)) for b in active_budgets(db, user)}

    seen = {c for s in (*spends, this_cycle) for c in s.by_category} - covered - {UNCATEGORISED}
    # At most SUGGEST_MAX, the categories with the most spending (concept 4.1).
    weight = {c: sum((s.by_category.get(c, Decimal(0)) for s in (*spends, this_cycle)), Decimal(0)) for c in seen}
    categories = sorted(sorted(seen, key=lambda c: (-weight[c], c))[:SUGGEST_MAX])
    suggestions = []
    for cat in categories:
        figures = [CycleFigure(start=c.start, end=c.end, spent=s.by_category.get(cat, Decimal(0)))
                   for c, s in zip(cycles, spends)]
        suggestions.append(BudgetSuggestion(
            category=cat, last_cycles=figures,
            suggested_limit=_round_up_10(statistics.median(f.spent for f in figures)) if enough else None,
            reason=None if enough else "not_enough_history",
            current_limit=current.get(cat),
        ))
    return BudgetSuggestResponse(suggestions=suggestions, commitment_covered=sorted(covered))
