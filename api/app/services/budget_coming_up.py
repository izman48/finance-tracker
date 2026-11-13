"""Coming up: a budget's commitment instalments still due this cycle (T-24-3).

A hint only: never part of `spent`, `over_by` or the pace status. The
instalments are the ones the forecast schedules (`held_scheduled_outflows`:
Claude's pending changes held, card-tied bills dropped as the forecast drops
them), due after today and on or before the cycle's last day, so coming up
never holds an instalment the forecast does not. Each goes to its
commitment's category (`commitment_categories`), compared to the budget's
by exact text. A £0 rule or one linked to a loan or holding adds nothing
(B-34: nothing invented). Everything is the caller's own rows.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import CommitmentDirection, CommitmentRule
from app.services.analytics.common import _d
from app.services.commitment_category import commitment_categories
from app.services.linked_commitments import linked_commitment_ids

ITEMS_MAX = 5


@dataclass(frozen=True)
class Instalment:
    commitment_id: uuid.UUID
    label: str
    due_date: date
    amount: Decimal


@dataclass(frozen=True)
class ComingUp:
    instalments: list[Instalment] = field(default_factory=list)

    @property
    def amount(self) -> Decimal:
        return sum((i.amount for i in self.instalments), Decimal(0))


def coming_up_by_category(db: Session, user, today: date, cycle_end: date,
                          categories: set[str]) -> dict[str, ComingUp]:
    """For each of `categories`, the instalments due in (today, cycle_end],
    earliest first."""
    from app.services.analytics.forecast import held_scheduled_outflows

    if not categories or cycle_end <= today:
        return {}
    occurrences, _ = held_scheduled_outflows(db, user, today + timedelta(days=1), cycle_end)
    out = budgeted_instalments(db, user, occurrences, categories)
    return {c: ComingUp(items) for c, items in out.items()}


def budgeted_instalments(db: Session, user, occurrences, categories: set[str]) -> dict[str, list[Instalment]]:
    """The expense instalments among `occurrences` (from one
    `held_scheduled_outflows` call) whose commitment's category is one of
    `categories`, earliest first. A £0 rule or one linked to a loan or
    holding adds nothing (B-34). Coming up and the dotted line both read
    this, each with the occurrences of its own window (T-24-3b)."""
    linked = linked_commitment_ids(db, user.id)
    due = [(v, d) for v, d in occurrences
           if v.direction == CommitmentDirection.EXPENSE.value and _d(v.amount) > 0 and v.id not in linked]
    if not due or not categories:
        return {}
    ids = {v.id for v, _ in due}
    rules = db.query(CommitmentRule).filter(CommitmentRule.user_id == user.id, CommitmentRule.id.in_(ids)).all()
    category_of = commitment_categories(db, user, rules)
    out: dict[str, list[Instalment]] = defaultdict(list)
    for version, day in sorted(due, key=lambda o: o[1]):
        category = category_of.get(version.id)
        if category in categories:
            out[category].append(Instalment(version.id, version.label, day, _d(version.amount)))
    return dict(out)
