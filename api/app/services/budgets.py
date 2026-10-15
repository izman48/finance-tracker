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
    CycleSummary,
    FirstOver,
    CycleFigure,
    NotCounted,
)
from app.services.analytics.commitments import held_next_payday, held_payday_dates, last_payday
from app.services.analytics.common import _today
from app.services.budget_spend import UNCATEGORISED, BudgetSpend, budget_spend

FALLBACK_DAYS = 30
# How far past the horizon to look for the payday ending its last cycle (as next_payday does).
PAYDAY_LOOKAHEAD_DAYS = 400
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
    # A pending Claude move of payday closer doesn't shorten the cycle, so it
    # can't lift the "after budgets" strip before the user keeps it (T-12-9d).
    nxt = held_next_payday(db, user, today + timedelta(days=1))
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
class CycleBudgets:
    """This cycle's budgets and spend: GET /budgets and the forecast's
    budget_projection both read them, so "left" is one number (T-09-14)."""

    cycle: Cycle
    days_total: int
    elapsed: int
    days_left: int
    spend: BudgetSpend
    budgets: list[Budget]
    # Active, unpaused budgets: the limits, their spend, and what's left
    # (each max(0, limit - spent), so overspending never adds back).
    total_limit: Decimal
    spent: Decimal
    left: Decimal


def cycle_budgets(db: Session, user, today: date) -> CycleBudgets:
    cycle = current_cycle(db, user, today)
    spend = budget_spend(db, user, cycle.start, cycle.end)
    days_total = (cycle.end - cycle.start).days + 1
    budgets = active_budgets(db, user)
    counting = [b for b in budgets if not b.paused]
    spent = [spend.by_category.get(b.category, Decimal(0)) for b in counting]
    return CycleBudgets(
        cycle=cycle, days_total=days_total,
        elapsed=min(days_total, (today - cycle.start).days + 1),
        days_left=max((cycle.end - today).days, 0),
        spend=spend, budgets=budgets,
        total_limit=sum((Decimal(b.limit_pounds) for b in counting), Decimal(0)),
        spent=sum(spent, Decimal(0)),
        left=sum((max(Decimal(0), Decimal(b.limit_pounds) - x) for b, x in zip(counting, spent)), Decimal(0)),
    )


def budget_list(db: Session, user, markers: dict | None = None,
                include_categories: bool = False) -> BudgetListResponse:
    """GET /budgets: the current cycle, each budget's spend and pace, other
    spending, what's not counted, and the cycle summary. The
    budgetable categories read a year of transactions (about 160 ms on 2,000
    of them), so they're only computed when asked for (eng-a on #156)."""
    inputs = cycle_budgets(db, user, _today())
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
    # The one most over (ties by category), for "Shopping is £20 over".
    over = sorted((r for r in rows if r.status == "over"), key=lambda r: (-r.over_by, r.category))
    first_over = FirstOver(category=over[0].category, over_by=over[0].over_by) if over else None
    tracking = [r for r in rows if r.status is not None]  # paused budgets leave the Home line (BM7)
    summary = BudgetSummary(
        budget_count=len(tracking),
        on_pace_count=sum(r.status in ("under_pace", "on_pace") for r in rows),
        first_over=first_over,
    )
    # ux 12a: "Your budgets: £890 this cycle. Spent £631, £259 left."
    this_cycle = CycleSummary(
        total_limit=_pence(inputs.total_limit), spent=_pence(inputs.spent), left=_pence(inputs.left),
        first_over=first_over, paused_count=sum(1 for b in inputs.budgets if b.paused),
    ) if inputs.budgets else None
    return BudgetListResponse(
        cycle=BudgetCycle(start=cycle.start, end=cycle.end, days_total=inputs.days_total,
                          days_left=inputs.days_left, fallback=cycle.fallback),
        summary=summary,
        budgets=rows, other_spending=other, total_spent=sum(spend.by_category.values(), Decimal(0)),
        not_counted=NotCounted(**spend.excluded), summary_this_cycle=this_cycle,
        budgetable_categories=sorted(budgetable_categories(db, user, _today())) if include_categories else None,
    )


# --- the Cashflow projection (T-09-4) -----------------------------------------------

def _pence(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(Decimal("0.01"))


def _later_cycles(db: Session, user, cycle: Cycle, until: date) -> list[Cycle]:
    """The cycles after `cycle` that start by `until`: payday to the day
    before the next one, as `current_cycle` finds them, from one read of the
    payday commitment."""
    start = cycle.end + timedelta(days=1)
    # Payday now and before Claude: each cycle ends at the later of the two,
    # so a pending payday move doesn't step the dotted line early (T-12-9d).
    now, before = held_payday_dates(db, user, start + timedelta(days=1), until + timedelta(days=PAYDAY_LOOKAHEAD_DAYS))
    out = []
    while start <= until and len(out) < 400:
        candidates = [d for d in (next((p for p in now if p > start), None),
                                  next((p for p in before if p > start), None)) if d]
        nxt = max(candidates) if candidates else None
        end = (nxt - timedelta(days=1)) if nxt else start + timedelta(days=FALLBACK_DAYS - 1)
        out.append(Cycle(start, end, fallback=False))
        start = end + timedelta(days=1)
    return out


def _spread(amount: Decimal, first: date, last: date, day: date) -> Decimal:
    """How much of `amount`, spread evenly over first..last, is used by `day`
    (all of it from `last` on; with no days to spread over, all at once)."""
    if day >= last:
        return amount
    days = (last - first).days + 1
    return amount * Decimal((day - first).days + 1) / Decimal(days)


def budget_projection(db: Session, user, forecast: dict) -> tuple[dict | None, str | None]:
    """The payday strip and the dotted line for a forecast response (T-09-14,
    the owner's rule): the solid line less the budgets, over the whole
    horizon. This cycle, what's left (`CycleBudgets.left`) spread evenly from
    today to the day before payday; each later cycle, the full total of the
    active, unpaused limits spread over its days, so the line rises with
    income as the solid line does. Unbudgeted spending is never projected.
    Null, with why: "no_budgets" (no active, unpaused budget) or
    "no_payday". Reads the forecast; never changes it."""
    from app.services.analytics.forecast import get_forecast

    today = _today()
    inputs = cycle_budgets(db, user, today)
    if inputs.total_limit <= 0:
        return None, "no_budgets"
    if inputs.cycle.fallback:
        return None, "no_payday"
    eve = inputs.cycle.end  # the day before payday
    timeline = [p for p in forecast["timeline"] if p["date"] >= today]
    payday_timeline = timeline
    if forecast["horizon_end"] < eve:
        payday_timeline = get_forecast(db, user, "payday")["timeline"]
    scheduled = Decimal([p for p in payday_timeline if p["date"] <= eve][-1]["balance"])

    horizon_end = timeline[-1]["date"] if timeline else today
    later = _later_cycles(db, user, inputs.cycle, horizon_end)

    def used_by(day: date) -> Decimal:
        # Today's point is on the solid line: the spread starts tomorrow,
        # unless today is the day before payday (eng-a on #154).
        used = Decimal(0) if day <= today < eve else _spread(inputs.left, today + timedelta(days=1), eve, day)
        for c in later:
            if day < c.start:
                break
            used += _spread(inputs.total_limit, c.start, c.end, day)
        return used

    series = [{"date": p["date"], "balance": _pence(Decimal(p["balance"]) - used_by(p["date"]))} for p in timeline]
    return {
        "payday": eve + timedelta(days=1),
        "scheduled_balance": scheduled,
        "after_budgets_balance": scheduled - inputs.left,
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
