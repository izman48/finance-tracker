"""Liabilities: amortisation and the figures derived from it (T-10-7a).

The user enters a liability's terms; everything else (payoff date, interest
left, total cost) is computed here at read time and never stored. Money stays
Decimal throughout.

APR is the effective yearly rate UK lenders quote, so the monthly rate is
(1 + APR)^(1/12) - 1. Each month interest is charged on the balance, rounded
half-up to the penny, then the payment is taken (the last payment clears what
is left). The entered balance is taken as the balance just after the last
payment, so the first scheduled payment carries a full month's interest.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.services.analytics.common import _add_months

# Bound on the schedule (sec, S T-10-7a): a payment barely above the interest
# must give a 422, never a loop that runs for centuries.
MAX_SCHEDULE_MONTHS = 600
PENNY = Decimal("0.01")


class PaymentTooLow(ValueError):
    """The payment never clears the balance (or not within the cap)."""

    def __init__(self, monthly_interest: Decimal, payment: Decimal):
        self.monthly_interest = monthly_interest
        self.payment = payment
        super().__init__(self.message)

    @property
    def message(self) -> str:
        if self.payment <= self.monthly_interest:
            return (
                f"A payment of £{self.payment} doesn't cover the first month's interest "
                f"of £{self.monthly_interest}. Increase the payment."
            )
        return (
            f"At £{self.payment} a month the balance would take more than "
            f"{MAX_SCHEDULE_MONTHS // 12} years to clear. Increase the payment."
        )


@dataclass(frozen=True)
class ScheduleRow:
    due_date: date
    interest: Decimal
    payment: Decimal
    balance_after: Decimal


@dataclass(frozen=True)
class Schedule:
    rows: list[ScheduleRow]

    @property
    def payoff_date(self) -> date:
        return self.rows[-1].due_date

    @property
    def interest_remaining(self) -> Decimal:
        return sum((r.interest for r in self.rows), Decimal("0.00"))

    @property
    def total_cost(self) -> Decimal:
        return sum((r.payment for r in self.rows), Decimal("0.00"))


def monthly_rate(apr_pct: Decimal) -> Decimal:
    """Monthly rate from an effective annual rate given in percent."""
    return (1 + apr_pct / 100) ** (Decimal(1) / Decimal(12)) - 1


def amortise(balance: Decimal, apr_pct: Decimal, payment: Decimal, first_payment: date) -> Schedule:
    """Monthly schedule from `balance` until it reaches zero.

    Raises PaymentTooLow when the payment doesn't cover the first month's
    interest or the balance isn't cleared within MAX_SCHEDULE_MONTHS.
    """
    rate = monthly_rate(apr_pct)
    first_interest = _interest(balance, rate)
    if payment <= first_interest:
        raise PaymentTooLow(first_interest, payment)

    rows: list[ScheduleRow] = []
    remaining = balance
    for month in range(MAX_SCHEDULE_MONTHS):
        interest = _interest(remaining, rate)
        paid = min(payment, remaining + interest)
        remaining = remaining + interest - paid
        rows.append(ScheduleRow(_add_months(first_payment, month), interest, paid, remaining))
        if remaining == 0:
            return Schedule(rows)
    raise PaymentTooLow(first_interest, payment)


def _interest(balance: Decimal, rate: Decimal) -> Decimal:
    return (balance * rate).quantize(PENNY, rounding=ROUND_HALF_UP)
