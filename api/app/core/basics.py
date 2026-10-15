"""The day and decimal helpers every money path shares (T-12-8).

They live outside `app.services.analytics` so that importing them runs
nothing else: the holdings engine needs them, and taking them from
`analytics.common` ran the analytics package `__init__`, which imports the
holdings modules back (a cycle that broke `import app.services.holdings.inputs`
on its own). `analytics.common` re-exports these same objects, so code and
the test clock that patch `_today` see one function.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from app.core.clock import uk_today


def _today() -> date:
    """The UK day (T-11-9): every money path takes its day from here."""
    return uk_today()


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
