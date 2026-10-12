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
from sqlalchemy.exc import IntegrityError

from app.models import Account, Budget, BudgetNudge, Transaction
from app.schemas.budgets import (
    BUDGETS_PER_USER_MAX,
    BudgetCycle,
    BudgetListResponse,
    BudgetResponse,
    BudgetSuggestion,
    BudgetSuggestResponse,
    BudgetSummary,
    FirstOver,
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
CATEGORY_LOOKBACK_DAYS = 365
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


def budgetable_categories(db: Session, user, today: date, covered: set[str] | None = None) -> set[str]:
    """The categories a budget can track: those on the user's own purchases
    over the last year, through the same `classify_purchase` lens as budget
    spend, less those that are mostly commitments. Income, refunds and
    transfers never count against a budget, so a category seen only on them
    could never track anything (eng-a's live-stack check)."""
    purchases = budget_spend(db, user, today - timedelta(days=CATEGORY_LOOKBACK_DAYS), today).by_category
    if covered is None:
        covered = commitment_covered(db, user, today)
    return set(purchases) - covered - {UNCATEGORISED}


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
    today = _today()
    covered = commitment_covered(db, user, today)
    if any(c in covered for c in new):
        raise _refuse("That category is mostly commitments, which are already counted in safe to spend.")
    allowed = budgetable_categories(db, user, today, covered)
    if any(c not in allowed for c in new):
        raise _refuse("Budgets can only use categories you spend in.")


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
    return _as_utc(budget.held_from).date() >= cycle.start


def _as_utc(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def pace_inputs(db: Session, user, today: date) -> PaceInputs:
    cycle = current_cycle(db, user, today)
    spend = budget_spend(db, user, cycle.start, cycle.end)
    days_total = (cycle.end - cycle.start).days + 1
    elapsed = min(days_total, (today - cycle.start).days + 1)
    days_left = max((cycle.end - today).days, 0)

    budgets = active_budgets(db, user)
    cycle_start = datetime.combine(cycle.start, datetime.min.time(), timezone.utc)
    held = [
        b for b in db.query(Budget).filter(Budget.user_id == user.id, Budget.held_from >= cycle_start)
        if _held_this_cycle(b, cycle)
    ]
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


def hold(db: Session, user, budget: Budget) -> None:
    """Paused or removed (by the user or Claude): for the rest of this cycle
    the category keeps counting at max(its remaining limit, its spend at
    pace) (sec's max rule, T-09-4). The hold outlives a resume or an undone
    removal (it's ignored while the budget is active and unpaused), so an
    undo that pauses or removes it again brings the same hold back; and a
    second hold in the same cycle never lowers the first (sec on #162)."""
    cycle = current_cycle(db, user, _today())
    remaining = remaining_now(db, user, budget)
    if budget.held_from is not None and _as_utc(budget.held_from).date() >= cycle.start:
        budget.held_remaining = max(Decimal(budget.held_remaining or 0), remaining)
        return
    budget.held_from = datetime.now(timezone.utc)
    budget.held_remaining = remaining


def remaining_now(db: Session, user, budget: Budget) -> Decimal:
    """The budget's remaining limit this cycle, for the hold when it is
    paused or removed."""
    cycle = current_cycle(db, user, _today())
    spent = budget_spend(db, user, cycle.start, cycle.end).by_category.get(budget.category, Decimal(0))
    return max(Decimal(0), Decimal(budget.limit_pounds) - spent)


def budget_list(db: Session, user, markers: dict | None = None,
                include_categories: bool = False) -> BudgetListResponse:
    """GET /budgets: the current cycle, each budget's spend and pace, other
    spending, what's not counted, and the reconciliation line. The
    budgetable categories read a year of transactions (about 160 ms on 2,000
    of them), so they're only computed when asked for (eng-a on #156)."""
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
    # The one most over (ties by category), for "Shopping is £20 over".
    over = sorted((r for r in rows if r.status == "over"), key=lambda r: (-r.over_by, r.category))
    tracking = [r for r in rows if r.status is not None]  # paused budgets leave the Home line (BM7)
    summary = BudgetSummary(
        budget_count=len(tracking),
        on_pace_count=sum(r.status in ("under_pace", "on_pace") for r in rows),
        first_over=FirstOver(category=over[0].category, over_by=over[0].over_by) if over else None,
    )
    return BudgetListResponse(
        cycle=BudgetCycle(start=cycle.start, end=cycle.end, days_total=inputs.days_total,
                          days_left=inputs.days_left, fallback=cycle.fallback),
        summary=summary,
        budgets=rows, other_spending=other, total_spent=sum(spend.by_category.values(), Decimal(0)),
        not_counted=NotCounted(**spend.excluded), reconciliation=reconciliation,
        budgetable_categories=sorted(budgetable_categories(db, user, _today())) if include_categories else None,
    )


# --- the Cashflow projection (T-09-4) -----------------------------------------------

def budget_projection(db: Session, user, forecast: dict) -> tuple[dict | None, str | None]:
    """The payday strip and dotted line for a forecast response (concept
    section 12), from the same inputs as the reconciliation line, and why
    it's missing when it is ("no_budgets" or "no_payday", BC2/BC3). Reads
    the forecast; never changes it."""
    from app.services.analytics.forecast import get_forecast

    today = _today()
    inputs = pace_inputs(db, user, today)
    if not inputs.any_budget:
        return None, "no_budgets"
    if inputs.cycle.fallback:
        return None, "no_payday"
    eve = inputs.cycle.end  # the day before payday
    timeline = forecast["timeline"]
    if forecast["horizon_end"] < eve:
        timeline = get_forecast(db, user, "payday")["timeline"]
    before = [p for p in timeline if p["date"] <= eve]
    scheduled = Decimal(before[-1]["balance"])

    stick_total = inputs.budgets_left + inputs.other_at_pace
    span = (eve - today).days

    def spent_by(day: date) -> Decimal:
        """The stick-to-budgets total spread evenly from today, all of it by
        the day before payday (eng-a on #154: on that day itself, all of it)."""
        return stick_total if span <= 0 else stick_total * Decimal((day - today).days) / Decimal(span)

    series = [
        {"date": p["date"], "balance": (Decimal(p["balance"]) - spent_by(p["date"])).quantize(Decimal("0.01"))}
        for p in forecast["timeline"] if today <= p["date"] <= eve
    ]
    from app.services.analytics.summary import get_summary

    headroom = Decimal(get_summary(db, user)["safe_to_spend"]) - stick_total  # the reconciliation line's
    stick = scheduled - stick_total
    return {
        "payday": eve + timedelta(days=1),
        "scheduled_balance": scheduled,
        "stick_to_budgets_balance": stick,
        "current_pace_balance": scheduled - inputs.all_at_pace,
        "headroom": headroom,
        "difference": stick - headroom,
        "series": series,
    }, None


# --- nudges (T-09-4b) ------------------------------------------------------------------

AT_LIMIT, PACE = "at_limit", "pace"


def _money(amount: Decimal) -> str:
    return f"£{amount:,.0f}" if amount == amount.to_integral_value() else f"£{amount:,.2f}"


def _left(days: int) -> str:
    if days <= 0:
        return "on the last day of this pay cycle"
    return f"with {days} day left" if days == 1 else f"with {days} days left"


def budget_nudges(db: Session, user) -> list[dict]:
    """The in-app budget nudges for /analytics/nudges: at the limit, or ahead
    of pace in the first half of the cycle. Each fires at most once per
    budget and cycle (stored; a unique key stops two loads both firing),
    and stays dismissed. Fixed copy; the category is plain text."""
    listing = budget_list(db, user)
    cycle_start, days_left = listing.cycle.start, listing.cycle.days_left
    early = days_left >= listing.cycle.days_total / 2
    out = []
    for b in listing.budgets:
        if b.paused:
            continue
        limit = Decimal(b.limit_pounds)
        if b.spent >= limit:
            kind = AT_LIMIT
            # Exactly at the limit is still "kept", so it never says "over" (lead on #158).
            body = (
                f"{b.category} is {_money(b.spent - limit)} over its {_money(limit)} budget {_left(days_left)}."
                if b.spent > limit else
                f"{b.category} has reached its {_money(limit)} budget {_left(days_left)}."
            )
        elif b.status == "ahead_of_pace" and early:
            kind = PACE
            body = f"{b.category} is ahead of pace: {_money(b.spent)} of {_money(limit)} {_left(days_left)}."
        else:
            continue
        nudge = _fire(db, user, b.id, cycle_start, kind)
        if nudge is None or nudge.dismissed_at is not None:
            continue
        out.append({
            "id": f"budget-{nudge.id}", "rank": 10, "body": body,
            "detail": f"Spent {_money(b.spent)} of {_money(limit)} this pay cycle, from {cycle_start:%-d %b}.",
            "source": None, "as_of": cycle_start,
        })
    return out


def _fire(db: Session, user, budget_id, cycle_start: date, kind: str) -> BudgetNudge | None:
    """This budget's nudge of this kind for this cycle, made the first time."""
    def find():
        return (db.query(BudgetNudge)
                .filter(BudgetNudge.user_id == user.id, BudgetNudge.budget_id == budget_id,
                        BudgetNudge.cycle_start == cycle_start, BudgetNudge.kind == kind)
                .first())
    nudge = find()
    if nudge is None:
        db.add(BudgetNudge(user_id=user.id, budget_id=budget_id, cycle_start=cycle_start, kind=kind))
        try:
            db.commit()
        except IntegrityError:  # another load fired it first
            db.rollback()
        nudge = find()
    return nudge


def dismiss_nudge(db: Session, user, nudge_id) -> None:
    nudge = db.query(BudgetNudge).filter(BudgetNudge.id == nudge_id, BudgetNudge.user_id == user.id).first()
    if nudge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nudge not found")
    if nudge.dismissed_at is None:
        nudge.dismissed_at = datetime.now(timezone.utc)
        db.commit()


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
