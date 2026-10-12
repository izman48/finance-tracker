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
from datetime import date, datetime, timedelta, timezone
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
from app.services.budget_spend import UNCATEGORISED, BudgetSpend, budget_spend

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


def validate_categories(db: Session, user, categories: list[str], budgeted: set[str] = frozenset()) -> None:
    """Every category is listed once and is visible text. A new one (not in
    `budgeted`, the user's active budgets) must also be one of the user's own
    categories and not mostly commitments; an existing budget's limit can
    still be changed after its category becomes mostly commitments (lead on
    #150). Raises 422 with fixed words (the category is never echoed)."""
    if len(set(categories)) != len(categories):
        raise _refuse("Each category can appear only once.")
    if any(has_hidden_characters(c) or not c.strip() for c in categories):
        raise _refuse("That category isn't valid.")
    new = [c for c in categories if c not in budgeted]
    if not new:
        return
    known = user_categories(db, user)
    if any(c not in known for c in new):
        raise _refuse("Budgets can only use your existing categories.")
    covered = commitment_covered(db, user, _today())
    if any(c in covered for c in new):
        raise _refuse("That category is mostly commitments, which are already counted in safe to spend.")


def lock_user_budgets(db: Session, user) -> None:
    """Serialise budget writes per user (the user row, FOR UPDATE), so two
    requests at once can't both pass the 20 cap (lead on #150). A no-op on
    SQLite, which has one writer anyway."""
    from app.models import User

    db.query(User.id).filter(User.id == user.id).with_for_update().one()


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


@dataclass(frozen=True)
class PaceInputs:
    """Everything the reconciliation line (GET /budgets) and the payday strip
    (the forecast's budget_projection) are computed from, so they agree."""

    cycle: Cycle
    days_total: int
    elapsed: int
    days_left: int
    spend: BudgetSpend
    budgets: list[Budget]
    # Remaining budgets: max(limit - spent, 0) over active budgets, plus each
    # budget paused or removed this cycle at max(remaining then, its spend at
    # pace) (sec's rule: pausing or removing never raises the figures).
    budgets_left: Decimal
    # Spending in categories with no budget counted above, at the pace so far
    # for the rest of the cycle.
    other_at_pace: Decimal
    # All spending at the pace so far, for the rest of the cycle.
    all_at_pace: Decimal
    # True when any budget counts this cycle (active, or held).
    any_budget: bool


def _at_pace(amount: Decimal, elapsed: int, days_left: int) -> Decimal:
    return (amount / Decimal(elapsed) * Decimal(max(days_left, 0))).quantize(Decimal("0.01"))


def _held_this_cycle(budget: Budget, cycle: Cycle) -> bool:
    if budget.held_from is None or (budget.active and not budget.paused):
        return False
    held = budget.held_from if budget.held_from.tzinfo else budget.held_from.replace(tzinfo=timezone.utc)
    return held.date() >= cycle.start


def pace_inputs(db: Session, user, today: date) -> PaceInputs:
    cycle = current_cycle(db, user, today)
    spend = budget_spend(db, user, cycle.start, cycle.end)
    days_total = (cycle.end - cycle.start).days + 1
    elapsed = min(days_total, (today - cycle.start).days + 1)
    days_left = max((cycle.end - today).days, 0)

    budgets = active_budgets(db, user)
    held = [b for b in db.query(Budget).filter(Budget.user_id == user.id, Budget.held_from.is_not(None))
            if _held_this_cycle(b, cycle)]
    counted: dict[str, Decimal] = {}  # category -> what it takes off the balance
    for b in budgets:
        if not b.paused:
            spent = spend.by_category.get(b.category, Decimal(0))
            counted[b.category] = max(counted.get(b.category, Decimal(0)), max(Decimal(0), Decimal(b.limit_pounds) - spent))
    for b in held:
        pace = _at_pace(spend.by_category.get(b.category, Decimal(0)), elapsed, days_left)
        counted[b.category] = max(counted.get(b.category, Decimal(0)), Decimal(b.held_remaining or 0), pace)
    other = sum((v for k, v in spend.by_category.items() if k not in counted), Decimal(0))
    total = sum(spend.by_category.values(), Decimal(0))
    return PaceInputs(
        cycle=cycle, days_total=days_total, elapsed=elapsed, days_left=days_left, spend=spend, budgets=budgets,
        budgets_left=sum(counted.values(), Decimal(0)),
        other_at_pace=_at_pace(other, elapsed, days_left),
        all_at_pace=_at_pace(total, elapsed, days_left),
        any_budget=bool(counted),
    )


def remaining_now(db: Session, user, budget: Budget) -> Decimal:
    """The budget's remaining limit this cycle, for the hold when it is
    paused or removed."""
    cycle = current_cycle(db, user, _today())
    spent = budget_spend(db, user, cycle.start, cycle.end).by_category.get(budget.category, Decimal(0))
    return max(Decimal(0), Decimal(budget.limit_pounds) - spent)


def budget_list(db: Session, user, markers: dict | None = None) -> BudgetListResponse:
    """GET /budgets: the current cycle, each budget's spend and pace, other
    spending, what's not counted, and the reconciliation line."""
    from app.services.analytics.summary import get_summary

    inputs = pace_inputs(db, user, _today())
    cycle, spend = inputs.cycle, inputs.spend
    share = Decimal(inputs.elapsed) / Decimal(inputs.days_total)
    rows = []
    for b in inputs.budgets:
        limit = Decimal(b.limit_pounds)
        spent = spend.by_category.get(b.category, Decimal(0))
        pace = (limit * share).quantize(Decimal("0.01"))
        rows.append(BudgetResponse(
            id=b.id, category=b.category, limit_pounds=int(limit), paused=b.paused, created_via=b.created_via,
            spent=spent, pace_spent=pace, over_by=max(Decimal(0), spent - limit),
            status=None if b.paused else _status(spent, pace, limit),
            changed_by_claude=(markers or {}).get(b.id),
        ))
    tracked = {b.category for b in inputs.budgets if not b.paused}
    other = sum((v for k, v in spend.by_category.items() if k not in tracked), Decimal(0))

    # No payday, no reconciliation (eng-a on #150): the 30-day fallback window
    # isn't the cycle safe-to-spend runs to.
    reconciliation = None
    if inputs.any_budget and not cycle.fallback:
        safe = Decimal(get_summary(db, user)["safe_to_spend"])
        reconciliation = Reconciliation(
            safe_to_spend=safe, budgets_left=inputs.budgets_left, other_at_pace=inputs.other_at_pace,
            headroom=safe - inputs.budgets_left - inputs.other_at_pace,
        )
    return BudgetListResponse(
        cycle=BudgetCycle(start=cycle.start, end=cycle.end, days_total=inputs.days_total,
                          days_left=inputs.days_left, fallback=cycle.fallback),
        budgets=rows, other_spending=other, total_spent=sum(spend.by_category.values(), Decimal(0)),
        not_counted=NotCounted(**spend.excluded), reconciliation=reconciliation,
    )


# --- the Cashflow projection (T-09-4) -----------------------------------------------

def budget_projection(db: Session, user, forecast: dict) -> dict | None:
    """The payday strip and dotted line for a forecast response (concept
    section 12), from the same inputs as the reconciliation line. Reads the
    forecast; never changes it. None with no budget counting this cycle or
    no payday."""
    from app.services.analytics.forecast import get_forecast

    today = _today()
    inputs = pace_inputs(db, user, today)
    if not inputs.any_budget or inputs.cycle.fallback:
        return None
    eve = inputs.cycle.end  # the day before payday
    timeline = forecast["timeline"]
    if forecast["horizon_end"] < eve:
        timeline = get_forecast(db, user, "payday")["timeline"]
    before = [p for p in timeline if p["date"] <= eve]
    scheduled = Decimal(before[-1]["balance"])

    stick_total = inputs.budgets_left + inputs.other_at_pace
    span = max((eve - today).days, 1)
    series = [
        {"date": p["date"],
         "balance": (Decimal(p["balance"]) - stick_total * Decimal(min((p["date"] - today).days, span)) / Decimal(span))
         .quantize(Decimal("0.01"))}
        for p in forecast["timeline"] if today <= p["date"] <= eve
    ]
    return {
        "payday": eve + timedelta(days=1),
        "scheduled_balance": scheduled,
        "stick_to_budgets_balance": scheduled - stick_total,
        "current_pace_balance": scheduled - inputs.all_at_pace,
        "series": series,
    }


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
