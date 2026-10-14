"""Liability amortisation (T-10-7a, liabilities spec stage 1).

The fixture is synthetic (the repo is public): £9,000 left, £200 a month,
11% APR. APR is the effective yearly rate UK lenders quote, so the monthly
rate is (1 + APR)^(1/12) - 1, not APR / 12 (and (1 + APR)^(1/n) - 1 for n
payments a year).

Hand-checked schedule (interest rounded half-up to the penny each month,
charged before the payment):

    month  balance in  interest  payment  balance out
        1   9,000.00     78.61   200.00    8,878.61
        2   8,878.61     77.55   200.00    8,756.16
        3   8,756.16     76.48   200.00    8,632.64
      ...
       57                 2.45   200.00       82.50
       58      82.50      0.72    83.22        0.00

58 payments, £2,483.22 interest, £11,483.22 paid in total.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.services.liabilities import (
    MAX_SCHEDULE_YEARS,
    PaymentTooLow,
    amortise,
    first_payment_after,
    next_payment_on,
    period_rate,
)

BALANCE = Decimal("9000.00")
APR = Decimal("11.00")
PAYMENT = Decimal("200.00")
FIRST_PAYMENT = date(2026, 11, 1)


def test_monthly_rate_is_the_effective_apr_compounded_monthly():
    rate = period_rate(APR, "monthly")
    assert (1 + rate) ** 12 == pytest.approx(Decimal("1.11"), abs=Decimal("1e-20"))
    assert rate.quantize(Decimal("0.0000001")) == Decimal("0.0087346")
    assert isinstance(rate, Decimal)


def test_amortisation_schedule_matches_lender_statement():
    schedule = amortise(BALANCE, APR, PAYMENT, FIRST_PAYMENT)

    first_three = [(r.due_date, r.interest, r.payment, r.balance_after) for r in schedule.rows[:3]]
    assert first_three == [
        (date(2026, 11, 1), Decimal("78.61"), Decimal("200.00"), Decimal("8878.61")),
        (date(2026, 12, 1), Decimal("77.55"), Decimal("200.00"), Decimal("8756.16")),
        (date(2027, 1, 1), Decimal("76.48"), Decimal("200.00"), Decimal("8632.64")),
    ]
    last = schedule.rows[-1]
    assert (last.interest, last.payment, last.balance_after) == (
        Decimal("0.72"), Decimal("83.22"), Decimal("0.00"),
    )
    assert len(schedule.rows) == 58
    assert schedule.interest_remaining == Decimal("2483.22")
    assert schedule.total_cost == Decimal("11483.22")
    assert all(isinstance(r.balance_after, Decimal) for r in schedule.rows)


def test_payoff_date_derived_from_balance_apr_and_payment():
    schedule = amortise(BALANCE, APR, PAYMENT, FIRST_PAYMENT)
    # 58 monthly payments from 1 Nov 2026: the last falls 57 months later.
    assert schedule.payoff_date == date(2031, 8, 1)


def test_payment_day_past_the_end_of_a_short_month_is_kept():
    schedule = amortise(BALANCE, APR, PAYMENT, date(2027, 1, 31))
    assert [r.due_date for r in schedule.rows[:3]] == [
        date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31),
    ]


def test_zero_apr_divides_the_balance_into_payments():
    schedule = amortise(Decimal("1000.00"), Decimal("0"), Decimal("300.00"), FIRST_PAYMENT)
    assert [r.payment for r in schedule.rows] == [
        Decimal("300.00"), Decimal("300.00"), Decimal("300.00"), Decimal("100.00"),
    ]
    assert schedule.interest_remaining == Decimal("0.00")
    assert schedule.payoff_date == date(2027, 2, 1)


def test_payment_that_does_not_cover_the_monthly_interest_is_refused():
    with pytest.raises(PaymentTooLow) as exc:
        amortise(BALANCE, APR, Decimal("78.61"), FIRST_PAYMENT)
    assert exc.value.first_interest == Decimal("78.61")


def test_payment_of_interest_plus_a_penny_stops_at_the_cap_and_is_refused():
    # It would clear the balance only after centuries; the loop stops at the cap.
    with pytest.raises(PaymentTooLow):
        amortise(BALANCE, APR, Decimal("78.62"), FIRST_PAYMENT)
    assert MAX_SCHEDULE_YEARS * 12 == 600


@pytest.mark.parametrize("cadence, per_year", [("weekly", 52), ("fortnightly", 26), ("four_weekly", 13)])
def test_rate_per_payment_follows_the_cadence(cadence, per_year):
    rate = period_rate(APR, cadence)
    assert (1 + rate) ** per_year == pytest.approx(Decimal("1.11"), abs=Decimal("1e-20"))


def test_weekly_payments_step_seven_days_and_clear_the_balance():
    schedule = amortise(Decimal("500.00"), Decimal("0"), Decimal("200.00"), date(2026, 11, 2), "weekly")
    assert [(r.due_date, r.payment) for r in schedule.rows] == [
        (date(2026, 11, 2), Decimal("200.00")),
        (date(2026, 11, 9), Decimal("200.00")),
        (date(2026, 11, 16), Decimal("100.00")),
    ]


def test_a_weekly_payment_that_never_clears_stops_at_the_cap():
    first_interest = (BALANCE * period_rate(APR, "weekly")).quantize(Decimal("0.01"))
    with pytest.raises(PaymentTooLow):
        amortise(BALANCE, APR, first_interest + Decimal("0.01"), FIRST_PAYMENT, "weekly")


# The start date sets the payment day; the balance on the as-of date already
# reflects any payment due that day, so the next payment is strictly after it.
@pytest.mark.parametrize("start, cadence, as_of, expected", [
    (date(2025, 3, 1), "monthly", date(2026, 10, 9), date(2026, 11, 1)),
    (date(2025, 3, 1), "monthly", date(2026, 11, 1), date(2026, 12, 1)),
    (date(2025, 1, 31), "monthly", date(2026, 2, 10), date(2026, 2, 28)),
    (date(2025, 1, 31), "monthly", date(2026, 3, 15), date(2026, 3, 31)),
    (date(2026, 12, 15), "monthly", date(2026, 10, 9), date(2026, 12, 15)),  # not started yet
    (date(2026, 10, 1), "weekly", date(2026, 10, 9), date(2026, 10, 15)),
    (date(2026, 10, 1), "weekly", date(2026, 10, 8), date(2026, 10, 15)),
    (date(2026, 10, 1), "fortnightly", date(2026, 10, 9), date(2026, 10, 15)),
    (date(2026, 9, 1), "four_weekly", date(2026, 10, 9), date(2026, 10, 27)),
])
def test_first_payment_after_the_as_of_date(start, cadence, as_of, expected):
    assert first_payment_after(start, cadence, as_of) == expected


# The schedule runs from today's balance: the next payment is on or after
# today, and strictly after the as-of date (that day's payment is in the balance).
@pytest.mark.parametrize("as_of, today, expected", [
    (date(2026, 8, 25), date(2026, 10, 9), date(2026, 11, 1)),   # old balance: never a past date
    (date(2026, 9, 20), date(2026, 10, 1), date(2026, 10, 1)),   # due today, not yet in the balance
    (date(2026, 10, 1), date(2026, 10, 1), date(2026, 11, 1)),   # as-of today: today's payment is in it
    (date(2026, 9, 20), date(2026, 9, 25), date(2026, 10, 1)),
])
def test_next_payment_is_on_or_after_today_and_after_the_as_of_date(as_of, today, expected):
    assert next_payment_on(date(2025, 3, 1), "monthly", as_of, today) == expected
