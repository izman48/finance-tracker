"""Planned card payments and projected card bills count once (T-12-4a).

A planned item flagged `is_card_payment` pays a credit card (the user ticks
it; no card is chosen, and nothing is matched by name). The projected card
repayments (`repayment_events`) pay the same cards. In each pay window the
larger of the two totals counts and the other side's entries in that window
drop out: a manual bill larger than the projection counts in full, a smaller
one gives way to it. Never a subtraction, so what goes out is never
understated (sec T-12-4). A window with only one side keeps it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    planned: Decimal      # flagged planned card payments due in the window
    projected: Decimal    # projected card repayments due in the window

    @property
    def overlaps(self) -> bool:
        return self.planned > 0 and self.projected > 0

    @property
    def keeps_planned(self) -> bool:
        return self.planned >= self.projected


def pay_windows(start: date, end: date, paydays: list[date]) -> list[tuple[date, date]]:
    """[start, end] cut at each payday after `start`: each window runs up to
    the day before a payday (the money due before that pay)."""
    cuts = sorted(p for p in paydays if start < p <= end)
    windows, lo = [], start
    for p in cuts:
        windows.append((lo, p - timedelta(days=1)))
        lo = p
    windows.append((lo, end))
    return windows


def resolve(windows: list[tuple[date, date]], planned: list[tuple], repayments: list[dict]):
    """(kept planned, kept repayments, windows) for `planned` = (key, date,
    amount > 0) flagged card payments and `repayments` = repayment events.
    Entries outside every window are kept."""
    kept_planned, kept_repayments, out = list(planned), list(repayments), []
    for lo, hi in windows:
        p = sum((a for _, d, a in planned if lo <= d <= hi), Decimal(0))
        r = sum((Decimal(str(x["amount"])) for x in repayments if lo <= x["due_date"] <= hi), Decimal(0))
        window = Window(lo, hi, p, r)
        out.append(window)
        if not window.overlaps:
            continue
        if window.keeps_planned:
            kept_repayments = [x for x in kept_repayments if not lo <= x["due_date"] <= hi]
        else:
            kept_planned = [e for e in kept_planned if not lo <= e[1] <= hi]
    return kept_planned, kept_repayments, out
