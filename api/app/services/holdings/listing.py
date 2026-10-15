"""What Claude may read about holdings (T-11-7; sec T-11-7).

A fixed set of keys per holding, from the same adapter and engine as net
worth and the graphs, so Claude's figures match the app's: value today (a
linked contribution paid since the last update included), when it was last
entered, the user's own growth %, the monthly contribution, whether it is a
linked bill, and projected values at 1, 5 and 10 years. Never the user id,
history, commitment ids or timestamps. Debts are not listed (sec / lead,
2026-10-15): loans, legacy debt assets and anything worth less than nothing
reach Claude only as totals in `cashflow_summary`, so no lender name does.
At most `MAX_LISTED` holdings, with `truncated` when more exist.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Asset, CommitmentLink
from app.services.analytics.common import _today

from .inputs import asset_inputs
from .projection import HoldingInput, project_holding, value_on

MAX_LISTED = 100
HORIZONS = {"1y": 12, "5y": 60, "10y": 120}
# A holding with no growth % of its own uses the projection's default.
DEFAULT_GROWTH_PCT = Decimal("5")
PENNY = Decimal("0.01")


def list_holdings(db: Session, user) -> dict:
    today = _today()
    holdings = [h for h in asset_inputs(db, user, DEFAULT_GROWTH_PCT, today) if _listed(h, today)]
    linked = {str(a_id) for (a_id,) in db.query(CommitmentLink.asset_id).filter(
        CommitmentLink.user_id == user.id, CommitmentLink.asset_id.isnot(None))}
    own_growth = {str(a_id): pct for a_id, pct in db.query(Asset.id, Asset.assumed_growth_pct).filter(
        Asset.user_id == user.id)}
    return {
        "holdings": [_row(h, today, h.id in linked, own_growth.get(h.id)) for h in holdings[:MAX_LISTED]],
        "count": len(holdings),
        "truncated": len(holdings) > MAX_LISTED,
    }


def investments_total(db: Session, user) -> Decimal:
    """Value today of the investment kinds (owner D1): the same set and the
    same value as net worth's Investments and the "Include investments" box."""
    today = _today()
    values = (value_on(h, today) for h in asset_inputs(db, user, Decimal(0), today) if h.is_investment)
    return sum((v for v in values if v is not None), Decimal(0)).quantize(PENNY)


def _listed(h: HoldingInput, today: date) -> bool:
    """A holding with a value that isn't a debt (by kind or by sign)."""
    value = value_on(h, today)
    return value is not None and not h.is_debt and value >= 0


def _row(h: HoldingInput, today: date, linked: bool, own_growth: Decimal | None) -> dict:
    series = project_holding(h, today, max(HORIZONS.values())).forecast
    return {
        "id": h.id,
        "name": h.name,
        "kind": h.kind,
        "value": series[0][1],
        "value_as_of": max(d for d, _ in h.valuations if d <= today),
        # The user's own %; null when not set ("growth not set").
        "growth_pct": None if own_growth is None else Decimal(own_growth).quantize(PENNY),
        "monthly_contribution": h.monthly_contribution.quantize(PENNY),
        "linked": linked,
        "projected": {key: series[months][1] for key, months in HORIZONS.items()},
    }
