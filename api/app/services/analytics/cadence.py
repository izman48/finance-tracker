"""Cadence math: stepping dates forward/back and expanding commitment occurrences."""
from __future__ import annotations

from datetime import date, timedelta

from app.models import CommitmentCadence, CommitmentRule

from .common import _add_months


def _cadence_from_interval(avg_days: float) -> tuple[str, int | None, int | None]:
    """Map an average gap in days to (cadence, interval_days, interval_months)."""
    if avg_days <= 10:
        return CommitmentCadence.WEEKLY.value, None, None
    if 25 <= avg_days <= 35:
        return CommitmentCadence.MONTHLY.value, None, None
    if 80 <= avg_days <= 100:
        return CommitmentCadence.EVERY_N_MONTHS.value, None, 3
    if 170 <= avg_days <= 195:
        return CommitmentCadence.EVERY_N_MONTHS.value, None, 6
    return CommitmentCadence.CUSTOM_DAYS.value, max(1, round(avg_days)), None


def _step(d: date, cadence: str, interval_days: int | None, interval_months: int | None) -> date:
    if cadence == CommitmentCadence.WEEKLY.value:
        return d + timedelta(days=7)
    if cadence == CommitmentCadence.MONTHLY.value:
        return _add_months(d, 1)
    if cadence == CommitmentCadence.EVERY_N_MONTHS.value:
        return _add_months(d, interval_months or 1)
    return d + timedelta(days=interval_days or 30)


def _step_back(d: date, cadence: str, interval_days: int | None, interval_months: int | None) -> date:
    if cadence == CommitmentCadence.WEEKLY.value:
        return d - timedelta(days=7)
    if cadence == CommitmentCadence.MONTHLY.value:
        return _add_months(d, -1)
    if cadence == CommitmentCadence.EVERY_N_MONTHS.value:
        return _add_months(d, -(interval_months or 1))
    return d - timedelta(days=interval_days or 30)


def commitment_occurrences(rule: CommitmentRule, start: date, end: date) -> list[date]:
    """Dates on which a commitment falls within [start, end] (inclusive)."""
    out: list[date] = []
    d = rule.next_date
    # Roll forward to the window if next_date is in the past.
    guard = 0
    while d < start and guard < 600:
        d = _step(d, rule.cadence, rule.interval_days, rule.interval_months)
        guard += 1
    while d <= end and guard < 600:
        out.append(d)
        d = _step(d, rule.cadence, rule.interval_days, rule.interval_months)
        guard += 1
    return out
