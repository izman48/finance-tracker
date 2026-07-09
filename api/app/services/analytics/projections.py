"""Net-worth projection: "when do I hit £X" from stated assumptions.

Pure request-time arithmetic — no persisted model. The contribution either
comes from the user (custom) or is derived from their own cashflow model:
confirmed income commitments − confirmed bills − average everyday spending
(the noise-excluded trend, so transfers and card repayments — which move money
without changing wealth — don't distort it). Either way the arithmetic is
echoed back and the UI labels it "an estimate, not advice" — never a personal
recommendation (FCA line).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import CommitmentDirection, CommitmentRule, CommitmentStatus

from .cadence import commitment_occurrences
from .common import _add_months, _d, _today
from .net_worth import net_worth_history
from .spending import get_spending_trend

# Search horizon for "when is the target hit" (50 years), and the cap on how
# many monthly points we actually return for charting.
MAX_MONTHS = 600
DEFAULT_CHART_MONTHS = 120

# How much history feeds the "average everyday spending" leg of the derived
# contribution. Complete months only — the current partial month would bias low.
SPEND_AVG_MONTHS = 6


def _monthly_equivalent(rules: list[CommitmentRule], today: date) -> Decimal:
    """A fair per-month figure for mixed cadences: occurrences over the next
    12 months × amount, divided by 12 (so yearly bills weigh 1/12, weekly ~4.3×)."""
    year_out = _add_months(today, 12)
    total = sum(
        (_d(r.amount) * len(commitment_occurrences(r, today, year_out)) for r in rules),
        Decimal(0),
    )
    return total / 12


def derived_contribution(db: Session, user) -> dict:
    """Expected monthly net-worth contribution from the user's own cashflow:
    confirmed income − confirmed bills − average everyday spending.

    The spending leg uses the noise-excluded trend with commitments excluded
    (they're already counted as bills), averaged over complete months only.
    Can be negative — that's an honest drift-down projection, not an error.
    """
    today = _today()
    rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    income = _monthly_equivalent(
        [r for r in rules if r.direction == CommitmentDirection.INCOME.value], today
    )
    bills = _monthly_equivalent(
        [r for r in rules if r.direction == CommitmentDirection.EXPENSE.value], today
    )

    trend = get_spending_trend(db, user, months=SPEND_AVG_MONTHS + 1, exclude_commitments=True)
    this_month = f"{today.year}-{today.month:02d}"
    complete = [m for m in trend["months"] if m["month"] != this_month]
    avg_spending = (
        sum((_d(m["total"]) for m in complete), Decimal(0)) / len(complete)
        if complete
        else Decimal(0)
    )

    return {
        "income_monthly": _round2(income),
        "bills_monthly": _round2(bills),
        "avg_spending_monthly": _round2(avg_spending),
        "contribution": _round2(income - bills - avg_spending),
        "spending_months_sampled": len(complete),
    }


def net_worth_projection(
    db: Session,
    user,
    target_amount: Decimal | None = None,
    monthly_contribution: Decimal | None = None,
    annual_growth_pct: Decimal = Decimal("5"),
) -> dict:
    """Compound today's net worth forward month by month.

    value(t+1) = value(t) × (1 + r_monthly) + contribution, where r_monthly is
    the monthly-compounded equivalent of the annual assumption. With no custom
    contribution, it's derived from the user's cashflow (income − bills − avg
    spending) and the basis is returned so the UI shows the working. Negative
    contributions are allowed — drawdown is a legitimate projection.
    Returns a monthly timeline (for the dashed chart extension), the first
    month the target is reached (or None within 50 years), and the assumptions
    echoed back so the UI can show exactly what was computed.
    """
    today = _today()
    # Same reconstruction as the Wealth chart, so the projection extends the
    # line it's drawn on rather than a subtly different figure.
    current = Decimal(str(net_worth_history(db, user, months=1)[-1]["net_worth"]))

    growth = max(Decimal("-50"), min(annual_growth_pct, Decimal("50"))) / Decimal(100)
    monthly_rate = Decimal(str((1 + float(growth)) ** (1 / 12) - 1))

    basis: dict | None = None
    if monthly_contribution is None:
        basis = derived_contribution(db, user)
        contribution = basis["contribution"]
    else:
        contribution = monthly_contribution

    timeline: list[dict] = [{"date": today, "value": _round2(current)}]
    # Already there today (e.g. a target below current net worth) — say so,
    # rather than "not reached" when growth is negative.
    target_date: date | None = (
        today if target_amount is not None and current >= target_amount else None
    )
    value = current
    for m in range(1, MAX_MONTHS + 1):
        value = value * (1 + monthly_rate) + contribution
        when = _add_months(today, m)
        if target_amount is not None and target_date is None and value >= target_amount:
            target_date = when
        # Chart points: up to the target (plus a little context past it), or a
        # 10-year default when no target is set / it's far away.
        months_wanted = DEFAULT_CHART_MONTHS
        if target_date is not None:
            months_wanted = min(MAX_MONTHS, (target_date.year - today.year) * 12 + (target_date.month - today.month) + 6)
        if m <= months_wanted:
            timeline.append({"date": when, "value": _round2(value)})
        elif target_amount is None or target_date is not None:
            break

    return {
        "current_net_worth": _round2(current),
        "target_amount": target_amount,
        "target_date": target_date,
        "monthly_contribution": _round2(contribution),
        # Non-null when the contribution was derived from the user's cashflow —
        # the UI renders the working (income − bills − avg spending).
        "contribution_basis": basis,
        "annual_growth_pct": annual_growth_pct,
        "as_of": today,
        "timeline": timeline,
    }


def _round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))
