"""Netting paid-back marks into spending by category (T-03-4; PRD T-03-1 v2).

One rule for every figure that nets marks: budgets (`budget_spend`) and the
Spending purchases lens, drill and trend, so they agree (three-sources rule).

- A mark on a spend nets that spend, but only if the spend is one of the
  counted purchases passed in (in the range, and still counted as spending:
  a spend set to a transfer nets nothing, AC-29).
- A mark on a category nets that category when its credit arrived in the
  range, never below £0. The rest is excess: shown, never income.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models import Transaction
from app.services.repayment_marks import AppliedMark

UNCATEGORISED = "Uncategorized"


@dataclass(frozen=True)
class PaidBack:
    """One mark netted: "Sam £60, Pizza Express", £60, against the spend's
    name or the category."""
    label: str
    amount: Decimal
    against: str
    category: str


def net_paid_back(by_category: dict[str, Decimal], marks: list[AppliedMark],
                  counted: dict[uuid.UUID, Transaction], start: date,
                  end: date) -> tuple[list[PaidBack], dict[str, Decimal]]:
    """Take the marks off `by_category` in place: spend marks off the
    `counted` purchases, then category marks whose credit arrived in
    [start, end], each category floored at £0. A category with no purchases
    gets no line. Returns the marks netted and the excess by category."""
    netted: list[PaidBack] = []
    by_mark_category: dict[str, Decimal] = defaultdict(Decimal)
    for mark in marks:
        if mark.applied_amount <= 0:
            continue
        if mark.spend_id is not None:
            spend = counted.get(mark.spend_id)
            if spend is None:
                continue
            category = spend.category or UNCATEGORISED
            by_category[category] -= mark.applied_amount
            netted.append(PaidBack(mark.label, mark.applied_amount, spend.merchant_name or spend.description,
                                   category))
        elif mark.category is not None and start <= _utc_day(mark.credit_at) <= end:
            by_mark_category[mark.category] += mark.applied_amount
            netted.append(PaidBack(mark.label, mark.applied_amount, mark.category, mark.category))
    _, excess = floor_at_zero(by_category, by_mark_category)
    return netted, excess


def paid_back_by_spend(marks: list[AppliedMark]) -> dict[uuid.UUID, Decimal]:
    """{spend id: what its marks net}. The caller applies it only to spends
    it counts, in their own range."""
    out: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for mark in marks:
        if mark.spend_id is not None and mark.applied_amount > 0:
            out[mark.spend_id] += mark.applied_amount
    return dict(out)


def category_paid_back(marks: list[AppliedMark], start: date, end: date) -> dict[str, Decimal]:
    """{category: what its marks net}, for credits that arrived in [start, end]."""
    out: dict[str, Decimal] = defaultdict(Decimal)
    for mark in marks:
        if mark.category is not None and mark.applied_amount > 0 and start <= _utc_day(mark.credit_at) <= end:
            out[mark.category] += mark.applied_amount
    return dict(out)


def floor_at_zero(by_category: dict[str, Decimal],
                  marked: dict[str, Decimal]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Take category marks off `by_category` in place, never below £0. A
    category with no spending gets no line. Returns what was taken and the
    excess, by category."""
    taken: dict[str, Decimal] = {}
    excess: dict[str, Decimal] = {}
    for category, amount in marked.items():
        spent = by_category.get(category, Decimal(0))
        taken[category] = min(spent, amount)
        if category in by_category:
            by_category[category] = spent - taken[category]
        if amount > taken[category]:
            excess[category] = amount - taken[category]
    return taken, excess


def _utc_day(moment: datetime) -> date:
    # Ranges are UTC days, as the transaction queries that build them.
    return (moment.astimezone(timezone.utc) if moment.tzinfo else moment).date()
