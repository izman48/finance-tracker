"""Net-worth projection: "when do I hit £X" from stated assumptions.

Pure request-time arithmetic — no persisted model. The user supplies a target,
a monthly contribution and a growth assumption (the UI defaults contribution
from `get_summary`'s `savable`); we compound forward from today's net worth.
This is a factual calculation with visible assumptions, labelled "an estimate,
not advice" in the UI — never a personal recommendation (FCA line).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from .common import _add_months, _today
from .net_worth import net_worth_history

# Search horizon for "when is the target hit" (50 years), and the cap on how
# many monthly points we actually return for charting.
MAX_MONTHS = 600
DEFAULT_CHART_MONTHS = 120


def net_worth_projection(
    db: Session,
    user,
    target_amount: Decimal | None = None,
    monthly_contribution: Decimal = Decimal(0),
    annual_growth_pct: Decimal = Decimal("5"),
) -> dict:
    """Compound today's net worth forward month by month.

    value(t+1) = value(t) × (1 + r_monthly) + monthly_contribution, where
    r_monthly is the monthly-compounded equivalent of the annual assumption.
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
    contribution = max(Decimal(0), monthly_contribution)

    timeline: list[dict] = [{"date": today, "value": _round2(current)}]
    target_date: date | None = None
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
        "annual_growth_pct": annual_growth_pct,
        "as_of": today,
        "timeline": timeline,
    }


def _round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))
