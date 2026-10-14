"""Liabilities: amortisation and the figures derived from it (T-10-7a).

The user enters a liability's terms; everything else (payoff date, interest
left, total cost) is computed here at read time and never stored. Money stays
Decimal throughout.

APR is the effective yearly rate UK lenders quote, so the rate per payment is
(1 + APR)^(1/n) - 1 for n payments a year (monthly: (1 + APR)^(1/12) - 1).
Each period interest is charged on the balance, rounded half-up to the penny,
then the payment is taken (the last payment clears what is left).

The start date sets the payment day. The entered balance is the balance on
the as-of date with any payment due that day already taken, so the first
scheduled payment is the first one after the as-of date, and it carries a
full period's interest.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.models import Liability
from app.services.analytics.common import _add_months

# Bound on the schedule (sec, T-10-7a): a payment barely above the interest
# must give a 422, never a loop that runs for centuries. 600 months.
MAX_SCHEDULE_YEARS = 50
# Payments a year, and the step from one payment date to the next.
PERIODS_PER_YEAR = {"monthly": 12, "four_weekly": 13, "fortnightly": 26, "weekly": 52}
_WEEKS_PER_STEP = {"four_weekly": 4, "fortnightly": 2, "weekly": 1}
# An as-of balance older than this gets an "update your balance" prompt.
STALE_AFTER_DAYS = 90
PENNY = Decimal("0.01")


class PaymentTooLow(ValueError):
    """The payment never clears the balance (or not within the cap)."""

    def __init__(self, first_interest: Decimal, payment: Decimal):
        self.first_interest = first_interest
        self.payment = payment
        super().__init__(self.message)

    @property
    def message(self) -> str:
        if self.payment <= self.first_interest:
            return (
                f"A payment of £{self.payment} doesn't cover the interest of "
                f"£{self.first_interest} it would be charged. Increase the payment."
            )
        return (
            f"At £{self.payment} a payment the balance would take more than "
            f"{MAX_SCHEDULE_YEARS} years to clear. Increase the payment."
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


def period_rate(apr_pct: Decimal, cadence: str = "monthly") -> Decimal:
    """Rate per payment from an effective annual rate given in percent."""
    return (1 + apr_pct / 100) ** (Decimal(1) / PERIODS_PER_YEAR[cadence]) - 1


def payment_date(start: date, cadence: str, n: int) -> date:
    """The n-th payment date counting from `start` (n = 0 is `start`)."""
    if cadence == "monthly":
        return _add_months(start, n)
    return start + timedelta(weeks=_WEEKS_PER_STEP[cadence] * n)


def first_payment_after(start: date, cadence: str, balance_as_of: date) -> date:
    """The first payment date after the as-of date on the start date's cycle."""
    if start > balance_as_of:
        return start
    if cadence == "monthly":
        n = (balance_as_of.year - start.year) * 12 + balance_as_of.month - start.month
    else:
        n = (balance_as_of - start).days // (7 * _WEEKS_PER_STEP[cadence])
    while payment_date(start, cadence, n) <= balance_as_of:
        n += 1
    return payment_date(start, cadence, n)


def amortise(
    balance: Decimal, apr_pct: Decimal, payment: Decimal, first_payment: date, cadence: str = "monthly"
) -> Schedule:
    """Schedule from `balance` until it reaches zero.

    Raises PaymentTooLow when the payment doesn't cover the first period's
    interest or the balance isn't cleared within MAX_SCHEDULE_YEARS.
    """
    rate = period_rate(apr_pct, cadence)
    first_interest = _interest(balance, rate)
    if payment <= first_interest:
        raise PaymentTooLow(first_interest, payment)

    rows: list[ScheduleRow] = []
    remaining = balance
    for n in range(MAX_SCHEDULE_YEARS * PERIODS_PER_YEAR[cadence]):
        interest = _interest(remaining, rate)
        paid = min(payment, remaining + interest)
        remaining = remaining + interest - paid
        rows.append(ScheduleRow(payment_date(first_payment, cadence, n), interest, paid, remaining))
        if remaining == 0:
            return Schedule(rows)
    raise PaymentTooLow(first_interest, payment)


def _interest(balance: Decimal, rate: Decimal) -> Decimal:
    return (balance * rate).quantize(PENNY, rounding=ROUND_HALF_UP)


def current_balance(liability: Liability) -> Decimal:
    """Today's balance. Until payments are linked (T-10-8) nothing proves a
    payment was made, so it is the entered balance: assuming payments that
    never happened would understate the debt."""
    return liability.balance


def next_payment_on(start: date, cadence: str, balance_as_of: date, today: date) -> date:
    """The next payment: on or after today (never a past date), and after the
    as-of date, whose balance already reflects that day's payment."""
    return first_payment_after(start, cadence, max(balance_as_of, today - timedelta(days=1)))


def derived_figures(liability: Liability, today: date) -> dict:
    """The read-time figures for a stored liability. The schedule runs from
    today's balance and the next payment on or after today.

    The schedule figures are null when the user repays irregularly (they
    would be guesses), and also if a stored row's schedule no longer clears
    (terms are checked on write, but one bad row must not 500 the list)."""
    balance = current_balance(liability)
    figures: dict = {
        "current_balance": balance,
        "next_payment_date": None,
        "payments_remaining": None,
        "payoff_date": None,
        "interest_remaining": None,
        "total_cost": None,
        "balance_stale": (today - liability.balance_as_of).days > STALE_AFTER_DAYS,
    }
    if liability.opted_out or liability.payment is None:  # no payment only when opted out
        return figures
    first = next_payment_on(liability.start_date, liability.cadence, liability.balance_as_of, today)
    try:
        schedule = amortise(balance, liability.apr, liability.payment, first, liability.cadence)
    except PaymentTooLow:
        return figures
    return figures | {
        "next_payment_date": first,
        "payments_remaining": len(schedule.rows),
        "payoff_date": schedule.payoff_date,
        "interest_remaining": schedule.interest_remaining,
        "total_cost": schedule.total_cost,
    }
