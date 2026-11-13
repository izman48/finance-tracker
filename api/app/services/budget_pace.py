"""Which commitment payments sit on a budget's pace line at their real dates
(T-24-5, lead 2026-11-13; sec on #298).

Pace spreads only the flexible part of a limit; payments "placed" here sit
on the line where they were paid. Placing too much hides real overspending
(the unsafe side for pace), so each commitment places at most its amount
times its instalments due so far this cycle, and anything above that is
spread like any other purchase, so even a payment that matches (key and
amount within tolerance) places no more than the instalments due.

While a Claude change to a commitment is unkept, the cap is judged the
safer way for pace, which is the smaller: confirmed only if it was
confirmed before Claude too, the lower amount, the fewer instalments, and
the before-Claude match keys (a rename moves no payments onto the line).
A payment is matched by `classify_purchase`, the same predicate budget
spend used, with the one matcher built from that commitment's
before-Claude version (`build_commitment_matcher`). Placed is never more than the
budget's spent (net of friends' repayments).
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models import CommitmentDirection, CommitmentRule, CommitmentStatus
from app.services.analytics.cadence import _step_back, commitment_occurrences
from app.services.analytics.commitments import CommitmentMatcher, NO_COMMITMENTS, build_commitment_matcher
from app.services.analytics.common import _d
from app.services.analytics.spending import classify_purchase
from app.services.budget_spend import BudgetSpend
from app.services.claude_keep import claude_rows
from app.services.linked_commitments import linked_commitment_ids
from app.services.planning_writes import TARGETS

# The fields whose before-Claude value decides what a commitment may place.
_PLACE_FIELDS = ("label", "match_key", "amount", "status", "cadence", "interval_days", "interval_months",
                 "next_date")


@dataclass
class _Cap:
    matcher: CommitmentMatcher
    room: Decimal


def placed_commitments(db: Session, user, spend: BudgetSpend, start: date, today: date) -> dict[str, Decimal]:
    """Placed commitment payments by category in [start, today]."""
    if not spend.counted_commitments:
        return {}
    rules = (db.query(CommitmentRule)
             .filter(CommitmentRule.user_id == user.id,
                     CommitmentRule.direction == CommitmentDirection.EXPENSE.value)
             .all())
    rows = claude_rows(db, user.id, [r.id for r in rules])
    linked = linked_commitment_ids(db, user.id)
    caps = [_cap(r, [x for x in rows.get(r.id, []) if x.kept_at is None], start, today, linked) for r in rules]
    caps = [cap for cap in caps if cap.room > 0]
    transfers, roles, financed = spend.match_context
    placed: dict[str, Decimal] = defaultdict(Decimal)
    for tx in sorted(spend.counted_commitments, key=lambda t: (t.transaction_date, str(t.id))):
        left = _d(tx.amount)
        for cap in caps:
            if left <= 0 or cap.room <= 0:
                continue
            if classify_purchase(tx, transfers, roles, financed, cap.matcher) != "commitment":
                continue
            take = min(left, cap.room)
            cap.room -= take
            left -= take
            placed[tx.category] += take
    return dict(placed)


def placed_by_category(spend: BudgetSpend, placed: dict[str, Decimal]) -> dict[str, Decimal]:
    """Never more than a category's spent, so paid-back marks open no headroom."""
    return {c: min(amount, spend.by_category.get(c, Decimal(0))) for c, amount in placed.items()}


def _cap(rule: CommitmentRule, unkept: list, start: date, today: date, linked: set) -> _Cap:
    before = _before_claude(rule, unkept)
    confirmed = CommitmentStatus.CONFIRMED.value
    if rule.status != confirmed or before.status != confirmed:
        return _Cap(NO_COMMITMENTS, Decimal(0))
    due = min(len(_due_so_far(rule, start, today)), len(_due_so_far(before, start, today)))
    amount = min(_d(rule.amount), _d(before.amount))
    return _Cap(build_commitment_matcher([before], linked), amount * due)


def _before_claude(rule: CommitmentRule, unkept: list) -> SimpleNamespace:
    """The rule with every unkept Claude change to these fields reverted, newest first."""
    view = SimpleNamespace(id=rule.id, direction=rule.direction, ends_on=getattr(rule, "ends_on", None),
                           **{f: getattr(rule, f) for f in _PLACE_FIELDS})
    fields = TARGETS["commitment"].fields
    for entry in reversed(unkept):
        for change in json.loads(entry.changes):
            name = change["field"]
            if name in _PLACE_FIELDS:
                raw = change["before"]
                setattr(view, name, None if raw is None else fields[name](raw))
    return view


def _due_so_far(version, start: date, today: date) -> list[date]:
    """Instalment dates in [start, today]. The stored next date is usually
    ahead, so step back past `start` first (lessons, #210)."""
    if version.next_date is None:
        return []
    d, guard = version.next_date, 0
    while d >= start and guard < 600:
        d = _step_back(d, version.cadence, version.interval_days, version.interval_months)
        guard += 1
    walk = SimpleNamespace(next_date=d, cadence=version.cadence, interval_days=version.interval_days,
                           interval_months=version.interval_months, ends_on=getattr(version, "ends_on", None))
    return commitment_occurrences(walk, start, today)

