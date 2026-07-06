"""Planned items: payment plans, one-offs, and manual recurring movements."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models import CommitmentDirection, PlannedItem

from .cadence import _step
from .common import _d


def installment_amount(total, installments: int, apr=None, fee=None) -> Decimal:
    """Per-installment payment. Even split by default; simple interest + fee if set."""
    n = installments or 1
    base = _d(total)
    if fee:
        base += _d(fee)
    if apr:
        # Simple interest over the plan term (installments assumed ~monthly).
        base += _d(total) * (_d(apr) / Decimal(100)) * (Decimal(n) / Decimal(12))
    return (base / Decimal(n)).quantize(Decimal("0.01"))


def planned_events(item: PlannedItem, start: date, end: date) -> list[tuple]:
    """(date, signed_amount) movements for a planned item within [start, end]."""
    sign = Decimal(1) if item.direction == CommitmentDirection.INCOME.value else Decimal(-1)
    out: list[tuple] = []

    if item.kind == "one_off":
        if start <= item.start_date <= end:
            out.append((item.start_date, sign * _d(item.amount)))
        return out

    if item.kind == "installment_plan":
        per = installment_amount(item.total_amount, item.installments or 1, item.apr, item.fee_amount)
        d = item.start_date
        for _ in range(item.installments or 0):
            if start <= d <= end:
                out.append((d, sign * per))
            d = _step(d, item.cadence or "monthly", item.interval_days, item.interval_months)
        return out

    # recurring
    d = item.start_date
    guard = 0
    while d <= end and guard < 600:
        if d >= start and (item.end_date is None or d <= item.end_date):
            out.append((d, sign * _d(item.amount)))
        d = _step(d, item.cadence or "monthly", item.interval_days, item.interval_months)
        guard += 1
    return out
