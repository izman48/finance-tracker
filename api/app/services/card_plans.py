"""Card instalment plans: read-time figures and the net worth rule (T-12-5a).

The user enters a plan's terms as they stand: what is left, the monthly
instalment and fee, how many instalments remain and the next one's date.
Instalment dates that have passed come off at read time (fail-safe: a plan
whose instalments the card paid is not owed twice by the projection).

Net worth (owner D4, 2026-10-15): while a plan has its card, it is never
added on its own. A provider listed in PLAN_IN_CARD_BALANCE is observed to
include plans in the card's synced balance (counting it would double count);
any other provider's plan is hidden until confirmed, and the UI says so.
The list changes only by a code change with a synthetic fixture test, never
by a user or Claude. A plan whose card has gone (SET NULL on disconnect)
counts as standalone debt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, CardPlan
from app.services.analytics.common import _add_months

# Providers observed to include plan balances in the card balance (upper
# case, as `balance_sign` normalises them). None confirmed yet.
PLAN_IN_CARD_BALANCE: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PlanFigures:
    instalments_remaining: int
    balance: Decimal
    next_date: date | None
    final_date: date


def figures(plan: CardPlan, today: date) -> PlanFigures:
    """The plan today: instalment dates before today are taken as paid."""
    total = plan.instalments_remaining
    past = sum(1 for n in range(total) if _add_months(plan.next_date, n) < today)
    left = total - past
    balance = max(Decimal(0), Decimal(str(plan.balance)) - Decimal(str(plan.instalment)) * past)
    return PlanFigures(
        instalments_remaining=left,
        balance=balance.quantize(Decimal("0.01")),
        next_date=_add_months(plan.next_date, past) if left else None,
        final_date=_add_months(plan.next_date, total - 1),
    )


def monthly_total(plan: CardPlan) -> Decimal:
    """Instalment + fee, in pence: what the plan adds to each card payment."""
    return (Decimal(str(plan.instalment)) + Decimal(str(plan.fee))).quantize(Decimal("0.01"))


def owed_on(plan: CardPlan, today: date, day: date) -> Decimal:
    """What a standalone plan owes on `day`: today's balance, less the
    instalments due after today and on or before `day`."""
    return figures(plan, max(today, day + timedelta(days=1))).balance


def provider_confirmed(card: Account | None) -> bool:
    return card is not None and (card.provider_name or "").strip().upper() in PLAN_IN_CARD_BALANCE


def in_net_worth(plan: CardPlan) -> bool:
    """Only a plan whose card has gone counts on its own (owner D4)."""
    return plan.card_account_id is None


def standalone_plans(db: Session, user) -> list[CardPlan]:
    return db.query(CardPlan).filter(CardPlan.user_id == user.id, CardPlan.card_account_id.is_(None)).all()


def standalone_owed(db: Session, user, today: date, as_of: date | None = None) -> Decimal:
    """Standalone plans' balance today, counted from when each was entered."""
    return sum(
        (figures(p, today).balance for p in standalone_plans(db, user)
         if as_of is None or p.created_at is None or p.created_at.date() <= as_of),
        Decimal(0),
    )
