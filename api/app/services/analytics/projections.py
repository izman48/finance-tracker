"""Net-worth projection: everything projected together, from stated assumptions.

The aggregator's promise: one place where the cashflow model and the balance
sheet project forward as a whole. The model, component by component —

- **bank cash** is held flat (your buffer doesn't compound);
- **monthly surplus** comes from the same engine as the Cashflow forecast
  (confirmed commitments + planned items, month by month — not a flat average)
  minus average everyday spending, and is swept into investments compounding
  at the stated growth rate. Card repayments are excluded: they're
  net-worth-neutral (cash down, debt down), while spending ON credit is
  already counted via the purchases-lens average;
- **each asset** compounds at its own assumed rate (per-asset override,
  defaulting to the global rate; liabilities default to 0% = held flat, and a
  negative override approximates paydown).

Pure request-time arithmetic — every assumption is echoed back and the UI
labels it "an estimate, not advice", never a recommendation (FCA line).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Asset,
    CommitmentDirection,
    CommitmentRule,
    CommitmentStatus,
    PlannedItem,
)
from app.models.asset import LIABILITY_TYPES

from .cadence import commitment_occurrences
from .common import _add_months, _d, _today
from .net_worth import net_worth_history
from .planned import planned_events
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


def _monthly_rate(annual_pct: Decimal) -> Decimal:
    clamped = max(Decimal("-50"), min(annual_pct, Decimal("50"))) / Decimal(100)
    return Decimal(str((1 + float(clamped)) ** (1 / 12) - 1))


def monthly_surplus_series(db: Session, user, months: int, avg_spending: Decimal) -> list[Decimal]:
    """Per-month net cash surplus, from the same model as the Cashflow forecast.

    surplus(m) = commitment income − commitment expenses + planned items in
    that calendar month, minus average everyday spending. Card repayments are
    deliberately absent: repaying a card moves cash onto the card's balance —
    net worth doesn't change — and the spending that built the balance is
    already in the purchases-lens average.
    """
    today = _today()
    end = _add_months(today, months)
    buckets = [Decimal(0)] * (months + 1)

    def bucket(occ: date) -> int:
        # Month m covers (today + (m-1) months, today + m months], so an
        # occurrence later THIS month lands in month 1, not nowhere.
        diff = (occ.year - today.year) * 12 + (occ.month - today.month)
        m = diff if diff > 0 and occ <= _add_months(today, diff) else diff + 1
        return max(1, m)

    confirmed = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    for rule in confirmed:
        sign = Decimal(1) if rule.direction == CommitmentDirection.INCOME.value else Decimal(-1)
        for occ in commitment_occurrences(rule, today + timedelta(days=1), end):
            m = bucket(occ)
            if m <= months:
                buckets[m] += sign * _d(rule.amount)

    planned = (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == user.id, PlannedItem.active.is_(True))
        .all()
    )
    for item in planned:
        for occ_date, amount in planned_events(item, today + timedelta(days=1), end):
            m = bucket(occ_date)
            if m <= months:
                buckets[m] += _d(amount)

    return [buckets[m] - avg_spending for m in range(1, months + 1)]


def net_worth_projection(
    db: Session,
    user,
    target_amount: Decimal | None = None,
    monthly_contribution: Decimal | None = None,
    annual_growth_pct: Decimal = Decimal("5"),
) -> dict:
    """Project the whole balance sheet forward, month by month.

    total(m) = bank cash (flat) + swept surplus compounding at the growth rate
    + each asset compounding at its own assumed rate. The surplus is the
    cashflow engine's month-by-month figure (or the custom flat amount when
    given). Returns the timeline with per-point components, the first month
    the target is reached (None within 50 years), and every assumption echoed
    back so the UI can show exactly what was computed.
    """
    today = _today()
    # Same reconstruction as the Wealth chart, so the projection extends the
    # line it's drawn on rather than a subtly different figure.
    now_point = net_worth_history(db, user, months=1)[-1]
    bank_now = Decimal(str(now_point["bank"]))
    current = Decimal(str(now_point["net_worth"]))

    r_global = _monthly_rate(annual_growth_pct)

    # Per-asset components: latest value + a monthly rate from the per-asset
    # assumption (global default for assets, flat for liabilities).
    assets = db.query(Asset).filter(Asset.user_id == user.id).all()
    components: list[dict] = []
    for a in assets:
        if not a.valuations:
            continue
        value = _d(a.valuations[-1].value)
        if a.assumed_growth_pct is not None:
            pct = a.assumed_growth_pct
        elif a.asset_type in LIABILITY_TYPES:
            pct = Decimal(0)
        else:
            pct = annual_growth_pct
        components.append({
            "name": a.name,
            "value": value,
            "growth_pct": pct,
            "rate": _monthly_rate(pct),
            # Planned monthly saving into the asset (paydown on a liability).
            # The cash side already shows up in measured spending/bills, so
            # adding it here moves that money from "consumption" to "wealth"
            # rather than double-counting it.
            "contribution": _d(a.monthly_contribution) if a.monthly_contribution else Decimal(0),
            "is_liability": a.asset_type in LIABILITY_TYPES,
        })

    basis: dict | None = None
    if monthly_contribution is None:
        mode = "cashflow"
        basis = derived_contribution(db, user)
        surplus = monthly_surplus_series(db, user, MAX_MONTHS, basis["avg_spending_monthly"])
        # Display figure: the first year's average — the math uses the series.
        year1 = surplus[:12]
        display_contribution = sum(year1, Decimal(0)) / len(year1)
    else:
        mode = "custom"
        surplus = [monthly_contribution] * MAX_MONTHS
        display_contribution = monthly_contribution

    timeline: list[dict] = [{
        "date": today,
        "value": _round2(current),
        "cash": _round2(bank_now),
        "invested": Decimal("0.00"),
        "assets": _round2(current - bank_now),
    }]
    # Already there today (e.g. a target below current net worth) — say so,
    # rather than "not reached" when growth is negative.
    target_date: date | None = (
        today if target_amount is not None and current >= target_amount else None
    )
    # Surplus waterfall: positive months are swept into investments (which
    # compound); negative months drain the cash buffer first, then sell down
    # investments, and any shortfall beyond that sits at 0% — a deficit must
    # never compound at the GROWTH rate (that would model borrowing at +10%).
    cash = bank_now
    invested = Decimal(0)
    for m in range(1, MAX_MONTHS + 1):
        invested *= 1 + r_global
        s = surplus[m - 1]
        if s >= 0:
            invested += s
        else:
            cash += s
            if cash < 0:
                invested += cash  # buffer exhausted — draw from investments
                cash = Decimal(0)
                if invested < 0:
                    # Everything exhausted: park the shortfall as (negative)
                    # cash so it accrues nothing rather than compounding.
                    cash = invested
                    invested = Decimal(0)
        assets_value = Decimal(0)
        for c in components:
            c["value"] = c["value"] * (1 + c["rate"]) + c["contribution"]
            # A paid-off liability stops at zero — you don't keep paying it.
            if c["is_liability"] and c["value"] > 0:
                c["value"] = Decimal(0)
            assets_value += c["value"]
        value = cash + invested + assets_value
        when = _add_months(today, m)
        if target_amount is not None and target_date is None and value >= target_amount:
            target_date = when
        # Chart points: up to the target (plus a little context past it), or a
        # 10-year default when no target is set / it's far away.
        months_wanted = DEFAULT_CHART_MONTHS
        if target_date is not None:
            months_wanted = min(MAX_MONTHS, (target_date.year - today.year) * 12 + (target_date.month - today.month) + 6)
        if m <= months_wanted:
            timeline.append({
                "date": when,
                "value": _round2(value),
                "cash": _round2(cash),
                "invested": _round2(invested),
                "assets": _round2(assets_value),
            })
        elif target_amount is None or target_date is not None:
            break

    return {
        "current_net_worth": _round2(current),
        "target_amount": target_amount,
        "target_date": target_date,
        "monthly_contribution": _round2(display_contribution),
        # Non-null when the contribution was derived from the user's cashflow —
        # the UI renders the working (income − bills − avg spending).
        "contribution_basis": basis,
        "annual_growth_pct": annual_growth_pct,
        "mode": mode,
        "bank_component": _round2(bank_now),
        "asset_assumptions": [
            {
                "name": c["name"],
                "growth_pct": c["growth_pct"],
                "monthly_contribution": _round2(c["contribution"]),
            }
            for c in components
        ],
        "as_of": today,
        "timeline": timeline,
    }


def _round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))
