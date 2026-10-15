"""The holding projection engine (ADR-002, T-11-4).

One pure function projects every holding, whatever its kind. It never touches
the database: the registry adapter builds each `HoldingInput` in the request
from decrypted columns (the caller's DEK), and every surface that shows a
holding's future (the investment graphs, net worth, the target projection)
calls this, so they can't disagree.

Models, per the kind registry:

- **growth**: from the value today, each month the value grows by the
  monthly equivalent of the holding's yearly % (effective annual: a value
  grows exactly that % over a full year, r = (1 + p)^(1/12) - 1), then the
  monthly contribution is paid in at the month end. Accumulated unrounded,
  rounded to the penny at output, the arithmetic the Wealth projection has
  always used. A debt on this model (a legacy asset-liability, stored
  negative) stops at zero once paid off.
- **amortisation**: the value on each date is minus what the loan schedule
  says is owed (`owed_on`, supplied by the adapter), so loans keep their
  Sprint 10 behaviour. Any holding with `owed_on` takes its value from it.
- anything else (an unknown kind, or a kind with no model): the stored value
  held flat. Never dropped: money owed must not vanish from a forecast.

"Value today" is the latest valuation on or before today, plus any linked
contributions paid after it (they have left the bank, so they are in the
holding until the user next updates its value).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.services.analytics.common import _add_months

# Bounds (sec, T-11-4). The API rejects anything outside them with a 422;
# the engine refuses rather than clamping, so nothing is quietly changed.
MIN_GROWTH_PCT = Decimal("-100")
MAX_GROWTH_PCT = Decimal("50")
MAX_MONTHS = 600
PENNY = Decimal("0.01")
# Linked contributions count for at most this long after the valuation they
# add to (sec, ADR-002); after that the user updates the value.
PAID_WINDOW_DAYS = 90

Point = tuple[date, Decimal]


@dataclass(frozen=True)
class HoldingInput:
    id: str
    name: str
    kind: str
    model: str
    valuations: tuple[Point, ...] = ()  # sorted by date
    growth_pct: Decimal = Decimal(0)
    monthly_contribution: Decimal = Decimal(0)
    is_debt: bool = False
    # Which table it is stored in ("assets" or "liabilities"): net worth
    # shows liabilities as their own figure.
    source: str = "assets"
    # From the kind registry: the balance-sheet group and whether the
    # "Include investments" choice can hide it.
    group: str = "other"
    is_investment: bool = False
    # Linked contributions already paid (date, amount), ADR-002.
    paid_contributions: tuple[Point, ...] = ()
    # Amortisation only: what is owed on a date (positive).
    owed_on: Callable[[date], Decimal] | None = None


@dataclass(frozen=True)
class HoldingSeries:
    id: str
    name: str
    kind: str
    source: str
    history: list[tuple[date, Decimal | None]]
    # Unrounded, so totals are rounded once (no penny drift from summing
    # rounded parts). `forecast` is what any surface shows.
    exact: list[Point] = field(repr=False)

    @property
    def forecast(self) -> list[Point]:
        return [(d, _round(v)) for d, v in self.exact]


def exact_total_at(series: list[HoldingSeries], month: int) -> Decimal:
    """The holdings' combined value at forecast month `month`, unrounded, for
    a caller that adds it to other figures before rounding."""
    return sum((s.exact[month][1] for s in series), Decimal(0))


def total_at(series: list[HoldingSeries], month: int) -> Decimal:
    """The holdings' combined value at forecast month `month`, rounded once."""
    return _round(exact_total_at(series, month))


@dataclass(frozen=True)
class Projection:
    per_holding: list[HoldingSeries]
    total: list[Point]


def monthly_rate(annual_pct: Decimal) -> Decimal:
    """Monthly rate that compounds to `annual_pct` over twelve months."""
    if not MIN_GROWTH_PCT <= annual_pct <= MAX_GROWTH_PCT:
        raise ValueError(f"growth % must be between {MIN_GROWTH_PCT} and {MAX_GROWTH_PCT}")
    # The float round-trip is deliberate: it is the arithmetic the Wealth
    # projection has always used, so figures stay byte-identical. A pure
    # Decimal power would move every projection by fractions of a penny.
    return Decimal(str((1 + float(annual_pct) / 100) ** (1 / 12) - 1))


def value_on(holding: HoldingInput, day: date) -> Decimal | None:
    """The holding's value on `day` from its records, or None before it was
    tracked: the latest valuation on/before `day` plus contributions paid
    after that valuation, on/before `day` and within PAID_WINDOW_DAYS of it."""
    if holding.owed_on is not None:
        return -holding.owed_on(day)
    latest = None
    for valued_at, value in holding.valuations:
        if valued_at <= day:
            latest = (valued_at, value)
    if latest is None:
        return None
    since, value = latest
    until = min(day, since + timedelta(days=PAID_WINDOW_DAYS))
    paid = sum((amount for when, amount in holding.paid_contributions if since < when <= until), Decimal(0))
    return value + paid


def project_holding(
    holding: HoldingInput, today: date, months: int, history_points: list[date] | None = None,
) -> HoldingSeries:
    """History at `history_points` and a monthly forecast for `months` months
    (point 0 is today). An empty forecast means the holding has no value yet."""
    if not 0 <= months <= MAX_MONTHS:
        raise ValueError(f"months must be between 0 and {MAX_MONTHS}")
    history = [(p, _round(value_on(holding, p))) for p in history_points or []]
    return HoldingSeries(
        id=holding.id, name=holding.name, kind=holding.kind, source=holding.source,
        history=history, exact=_forecast(holding, today, months),
    )


def project_holdings(
    holdings: list[HoldingInput], today: date, months: int, history_points: list[date] | None = None,
) -> Projection:
    """Every holding with a value, and their total on each forecast date."""
    series = [project_holding(h, today, months, history_points) for h in holdings]
    series = [s for s in series if s.forecast]
    dates = [_add_months(today, m) for m in range(months + 1)]
    total = [(when, total_at(series, i)) for i, when in enumerate(dates)] if series else []
    return Projection(per_holding=series, total=total)


def _forecast(holding: HoldingInput, today: date, months: int) -> list[Point]:
    start = value_on(holding, today)
    if start is None:
        return []
    dates = [_add_months(today, m) for m in range(months + 1)]
    if holding.model == "amortisation":
        return [(d, value_on(holding, d)) for d in dates]
    if holding.model != "growth":
        return [(d, start) for d in dates]

    rate = monthly_rate(holding.growth_pct)
    value, out = start, [(today, start)]
    for d in dates[1:]:
        value = value * (1 + rate) + holding.monthly_contribution
        if holding.is_debt and value > 0:
            value = Decimal(0)  # paid off: you stop paying it
        out.append((d, value))
    return out


def _round(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(PENNY)
