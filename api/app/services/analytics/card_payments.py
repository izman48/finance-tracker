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


# How far ahead the overlap is looked for (the Cashflow forecast's longest view).
OVERLAP_HORIZON_DAYS = 92


def overlap_windows(db, user, today: date) -> list[tuple[Window, set]]:
    """Each pay window from today to 92 days ahead with the flagged planned
    items in it: (window, item ids). The summary's inputs, so the chip and
    nudge quote the figures safe-to-spend counts: bills as Claude's pending
    changes leave them (`counted_commitments`, for the card ties), projected
    card repayments, and active planned items plus any Claude removed that
    the user hasn't kept (`held_removed_planned`)."""
    from app.models import CommitmentDirection, PlannedItem
    from app.services.claude_keep import counted_commitments, held_removed_planned

    from .cadence import commitment_occurrences
    from .common import _d
    from .commitments import payday_dates
    from .planned import planned_expense_occurrences
    from .planned_matching import planned_states
    from .repayments import scheduled_outflows

    start, end = today, today + timedelta(days=OVERLAP_HORIZON_DAYS)
    rules = counted_commitments(
        db, user.id, CommitmentDirection.EXPENSE.value,
        lambda r: _d(r.amount) * len(commitment_occurrences(r, start, end)),
    )
    _, repayments = scheduled_outflows(db, user, rules, start, end)
    planned = db.query(PlannedItem).filter(
        PlannedItem.user_id == user.id, PlannedItem.active.is_(True),
    ).all() + held_removed_planned(db, user.id)
    states = planned_states(db, user, planned, today)
    flagged = [(item.id, d, a) for item, d, a in planned_expense_occurrences(planned, states, start, end)
               if item.is_card_payment]
    _, _, windows = resolve(pay_windows(start, end, payday_dates(db, user, start, end)), flagged, repayments)
    return [(w, {i for i, d, _ in flagged if w.start <= d <= w.end}) for w in windows]
