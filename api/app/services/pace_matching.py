"""Commitment payments the budget pace leaves out (T-09-13; sec's guards).

A confirmed commitment's stored match key can carry last month's bank
reference ("... 1606LANDMARKE FT", this month "... STO"), so this month's
payment doesn't key-match and `budget_spend` counts it as a purchase. Paced
forward, one rent payment on day 1 pulled the dotted line down by hundreds
of pounds a day. For the pace only (other_at_pace, all_at_pace and the pace
nudge), a purchase is taken for a commitment occurrence when it matches by:

(a) merchant: both keys without any token that contains a digit or is a
    bank transaction code, at least 2 tokens or 6 characters; or
(b) amount: within the planned-matching tolerance (2%), within 5 days of
    the occurrence's due date, for a commitment of at least £50.

Each occurrence due this cycle up to today takes at most one purchase
(merchant matches first, then amount; the nearest due date), so a second
matching purchase stays paced. Expense debits only: `budget_spend`'s
purchases are already the purchases lens (no credits, transfers, card
payoffs or key-matched commitments). Nothing else changes: the spend
figures, safe to spend, the summary, the forecast and Spending.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import CommitmentRule
from app.models.commitment_rule import CommitmentDirection, CommitmentStatus
from app.services.analytics.cadence import _step, _step_back
from app.services.analytics.commitments import _match_key
from app.services.analytics.planned_matching import tolerance
from app.services.budget_spend import Purchase

BANK_CODES = frozenset({"ddr", "sto", "ft", "bgc", "cpm", "dd", "so"})
AMOUNT_ONLY_MIN = Decimal(50)
AMOUNT_ONLY_DAYS = 5


def loose_merchant(match_key: str | None) -> str | None:
    """A match key without references or bank codes, or None if too short
    to match on."""
    if not match_key:
        return None
    _, _, text = match_key.partition(":")
    tokens = [t for t in text.split() if not any(c.isdigit() for c in t) and t not in BANK_CODES]
    joined = " ".join(tokens)
    return joined if joined and (len(tokens) >= 2 or len(joined) >= 6) else None


@dataclass(frozen=True)
class Occurrence:
    due: date
    amount: Decimal
    merchants: frozenset[str]


def _due_dates(rule: CommitmentRule, start: date, today: date) -> list[date]:
    """The rule's due dates in [start, today], stepping from next_date."""
    step = (rule.cadence, rule.interval_days, rule.interval_months)
    d, dates, guard = rule.next_date, [], 0
    if d > today:
        while d > today and guard < 600:
            d, guard = _step_back(d, *step), guard + 1
        while d >= start and guard < 1200:
            dates.append(d)
            d, guard = _step_back(d, *step), guard + 1
    else:
        while d <= today and guard < 600:
            if d >= start:
                dates.append(d)
            d, guard = _step(d, *step), guard + 1
    return dates


def occurrences(db: Session, user, start: date, today: date) -> list[Occurrence]:
    rules = (
        db.query(CommitmentRule)
        .filter(CommitmentRule.user_id == user.id, CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
                CommitmentRule.direction == CommitmentDirection.EXPENSE.value)
        .all()
    )
    out = []
    for r in rules:
        keys = {r.match_key, _match_key(r.direction, r.label) if r.label else None}
        merchants = frozenset(m for m in (loose_merchant(k) for k in keys) if m)
        out.extend(Occurrence(due=d, amount=Decimal(r.amount), merchants=merchants)
                   for d in _due_dates(r, start, today))
    return out


def _by_merchant(p: Purchase, o: Occurrence) -> bool:
    name = loose_merchant(p.match_key)
    return name is not None and name in o.merchants


def _by_amount(p: Purchase, o: Occurrence) -> bool:
    return (o.amount >= AMOUNT_ONLY_MIN and abs(p.amount - o.amount) <= tolerance(o.amount)
            and abs((p.day - o.due).days) <= AMOUNT_ONLY_DAYS)


def commitment_payments(db: Session, user, purchases: tuple[Purchase, ...], start: date,
                        today: date) -> dict[str, Decimal]:
    """{category: amount} of the purchases taken for a commitment occurrence."""
    free = occurrences(db, user, start, today)
    if not free:
        return {}
    ordered = sorted(enumerate(purchases), key=lambda ip: (ip[1].day, ip[0]))
    taken: set[int] = set()
    for matches in (_by_merchant, _by_amount):
        for i, p in ordered:
            if i in taken:
                continue
            candidates = [o for o in free if matches(p, o)]
            if candidates:
                free.remove(min(candidates, key=lambda o: abs((p.day - o.due).days)))
                taken.add(i)
    paid: dict[str, Decimal] = defaultdict(Decimal)
    for i in taken:
        paid[purchases[i].category] += purchases[i].amount
    return dict(paid)
