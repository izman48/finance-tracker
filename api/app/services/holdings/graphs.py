"""The investment graphs (T-11-4c, ux T-11-2 "Investments" view).

Each investment (registry `is_investment`, owner D1) and their total: the
valuations the user entered as history (nothing guessed between them, ux
A4), then the holding engine's monthly forecast, the same function as the
target projection. "Paid in" in the forecast is the value today plus the
contributions from today (ux A3: nilu can't know what was paid in before).
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.services.analytics.common import _today

from .inputs import holding_inputs
from .projection import HoldingInput, HoldingSeries, project_holdings, total_at, value_on

# A holding with no growth % of its own grows at the default the caller
# passes (the target form's growth %), so the graph and the projection agree.
DEFAULT_GROWTH_PCT = Decimal("5")
PENNY = Decimal("0.01")


def investment_graph(
    db: Session, user, months: int, holding_id: str | None = None,
    default_growth_pct: Decimal = DEFAULT_GROWTH_PCT,
) -> dict | None:
    """The graph payload, or None when `holding_id` is not one of the
    caller's investments (the route answers 404)."""
    today = _today()
    investments = [h for h in holding_inputs(db, user, today, default_growth_pct) if h.is_investment]
    if holding_id is not None:
        investments = [h for h in investments if h.id == holding_id]
        if not investments:
            return None
    projection = project_holdings(investments, today, months)
    inputs = {h.id: h for h in investments}
    holdings = [_holding(inputs[s.id], s, today) for s in projection.per_holding]
    shown = [inputs[s.id] for s in projection.per_holding]
    contribution = sum((h.monthly_contribution for h in shown), Decimal(0))
    value_today = total_at(projection.per_holding, 0) if holdings else Decimal("0.00")
    forecast = [
        {"date": when, "worth": worth, "paid_in": _q(value_today + contribution * m)}
        for m, (when, worth) in enumerate(projection.total)
    ]
    total = {
        "value_today": value_today,
        "monthly_contribution": _q(contribution),
        "history": _total_history(shown, today),
        "forecast": forecast,
        "answer": _answer(forecast, months),
    }
    return {"as_of": today, "months": months, "holdings": holdings, "total": total}


def _holding(h: HoldingInput, series: HoldingSeries, today: date) -> dict:
    value_today = series.forecast[0][1]
    return {
        "id": h.id,
        "name": h.name,
        "kind": h.kind,
        "value_today": value_today,
        "value_as_of": max(d for d, _ in h.valuations if d <= today),
        "growth_pct": h.growth_pct,
        "monthly_contribution": _q(h.monthly_contribution),
        "history": [{"date": d, "worth": _q(value_on(h, d))} for d, _ in h.valuations if d <= today],
        "forecast": [
            {"date": when, "worth": worth, "paid_in": _q(value_today + h.monthly_contribution * m)}
            for m, (when, worth) in enumerate(series.forecast)
        ],
    }


def _total_history(holdings: list[HoldingInput], today: date) -> list[dict]:
    """The total on each date any investment was valued: the sum of every
    investment tracked by then (one not yet tracked adds nothing)."""
    dates = sorted({d for h in holdings for d, _ in h.valuations if d <= today})
    points = []
    for d in dates:
        values = [v for v in (value_on(h, d) for h in holdings) if v is not None]
        points.append({"date": d, "worth": _q(sum(values, Decimal(0)))})
    return points


def _answer(forecast: list[dict], months: int) -> dict | None:
    """The sentence's figures at the end of the range, to the nearest
    £1,000 ("worth about £171,000, paid in £120,000")."""
    if not forecast:
        return None
    end = forecast[-1]
    return {"months": months, "worth_about": _thousand(end["worth"]), "paid_in": _thousand(end["paid_in"])}


def _thousand(value: Decimal) -> Decimal:
    return (value / 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP) * 1000


def _q(value: Decimal) -> Decimal:
    return value.quantize(PENNY)
