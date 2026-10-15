"""What Claude may read about holdings (T-11-7; sec T-11-7).

A fixed set of keys per holding, from the same adapter and engine as net
worth and the graphs, so Claude's figures match the app's: value today
(liabilities negative), when it was last entered, the user's growth %, the
monthly contribution or repayment, whether a bill is linked, and projected
values at 1, 5 and 10 years. Never the user id, history, commitment ids or
timestamps. At most `MAX_LISTED` holdings, with `truncated` when more exist.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import CommitmentLink, Liability
from app.services.analytics.common import _today

from .inputs import asset_inputs, holding_inputs
from .projection import HoldingInput, project_holding, value_on

MAX_LISTED = 100
HORIZONS = {"1y": 12, "5y": 60, "10y": 120}
# A holding with no growth % of its own uses the projection's default.
DEFAULT_GROWTH_PCT = Decimal("5")
PENNY = Decimal("0.01")


def list_holdings(db: Session, user) -> dict:
    today = _today()
    holdings = [h for h in holding_inputs(db, user, today, DEFAULT_GROWTH_PCT) if value_on(h, today) is not None]
    linked = _linked_ids(db, user)
    liabilities = {str(x.id): x for x in db.query(Liability).filter(Liability.user_id == user.id)}
    shown = holdings[:MAX_LISTED]
    return {
        "holdings": [_row(h, today, linked, liabilities.get(h.id)) for h in shown],
        "count": len(holdings),
        "truncated": len(holdings) > MAX_LISTED,
    }


def investments_total(db: Session, user) -> Decimal:
    """Value today of the investment kinds (owner D1): the same set and the
    same value as net worth's Investments and the "Include investments" box."""
    today = _today()
    values = (value_on(h, today) for h in asset_inputs(db, user, Decimal(0), today) if h.is_investment)
    return sum((v for v in values if v is not None), Decimal(0)).quantize(PENNY)


def _row(h: HoldingInput, today: date, linked: set[str], liability: Liability | None) -> dict:
    series = project_holding(h, today, max(HORIZONS.values())).forecast
    if liability is not None:
        value_as_of = liability.balance_as_of
        growth = None
        contribution = None if liability.opted_out or liability.payment is None else liability.payment
    else:
        value_as_of = max(d for d, _ in h.valuations if d <= today)
        growth = h.growth_pct
        contribution = h.monthly_contribution
    return {
        "id": h.id,
        "name": h.name,
        "kind": h.kind,
        "value": series[0][1],
        "value_as_of": value_as_of,
        "growth_pct": None if growth is None else Decimal(growth).quantize(PENNY),
        "monthly_contribution": None if contribution is None else Decimal(contribution).quantize(PENNY),
        "linked": h.id in linked,
        "projected": {key: series[months][1] for key, months in HORIZONS.items()},
    }


def _linked_ids(db: Session, user) -> set[str]:
    """Holdings whose payment is a linked bill: an asset's contribution or a
    loan's repayment."""
    ids = {str(row.asset_id or row.liability_id) for row in db.query(CommitmentLink).filter(
        CommitmentLink.user_id == user.id)}
    ids |= {str(x_id) for (x_id,) in db.query(Liability.id).filter(
        Liability.user_id == user.id, Liability.linked_commitment_id.isnot(None))}
    return ids
