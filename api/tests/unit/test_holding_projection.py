"""The holding projection engine (T-11-4, ADR-002).

One pure function projects every holding: valuation history up to today,
then a forecast from the value today. Growth holdings compound at the
holding's own yearly % (effective annual: a value grows that % over a full
year, r = (1 + p)^(1/12) - 1 a month) and add the monthly contribution at
each month end. Amortising holdings follow the loan schedule they are given.
An unknown model holds the stored value flat, never drops it.

All figures are synthetic.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.holdings.projection import (
    HoldingInput,
    project_holding,
    project_holdings,
    value_on,
)

TODAY = date(2026, 1, 15)


def _isa(**kw) -> HoldingInput:
    base = dict(
        id="isa-1", name="Test ISA", kind="isa", model="growth",
        valuations=((TODAY, Decimal("0")),),
        growth_pct=Decimal("7"), monthly_contribution=Decimal("1000"),
    )
    base.update(kw)
    return HoldingInput(**base)


def _hand_schedule(start: Decimal, pct: Decimal, contribution: Decimal, months: int) -> list[Decimal]:
    """The schedule written out step by step, independently of the engine:
    each month the value grows by the monthly equivalent of `pct` a year,
    then the contribution is paid in."""
    monthly = Decimal(str((1 + float(pct) / 100) ** (1 / 12) - 1))
    values, v = [], start
    for _ in range(months):
        v = v + v * monthly + contribution
        values.append(v.quantize(Decimal("0.01")))
    return values


class TestGrowthSchedule:
    def test_worked_example_matches_the_hand_checked_figure_to_the_penny(self):
        """£0, £1,000 a month, 7% a year, 10 years -> £171,051.73
        (sprint 11 worked example, effective-annual compounding)."""
        series = project_holding(_isa(), TODAY, months=120)
        assert series.forecast[-1] == (date(2036, 1, 15), Decimal("171051.73"))

    def test_every_month_matches_the_hand_schedule(self):
        series = project_holding(_isa(), TODAY, months=120)
        expected = _hand_schedule(Decimal("0"), Decimal("7"), Decimal("1000"), 120)
        assert [v for _, v in series.forecast[1:]] == expected

    def test_a_full_year_with_no_contribution_grows_by_exactly_the_yearly_rate(self):
        h = _isa(valuations=((TODAY, Decimal("10000")),), monthly_contribution=Decimal("0"))
        series = project_holding(h, TODAY, months=12)
        assert series.forecast[12][1] == Decimal("10700.00")

    def test_month_zero_is_the_value_today_on_today(self):
        h = _isa(valuations=((TODAY, Decimal("2500")),))
        assert project_holding(h, TODAY, months=3).forecast[0] == (TODAY, Decimal("2500.00"))

    def test_forecast_dates_step_a_calendar_month_from_today(self):
        h = _isa()
        dates = [d for d, _ in project_holding(h, date(2026, 1, 31), months=2).forecast]
        assert dates == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]


class TestValueTodayRebases:
    def test_the_forecast_starts_from_the_latest_valuation_on_or_before_today(self):
        h = _isa(
            valuations=(
                (date(2025, 1, 15), Decimal("1000")),
                (TODAY, Decimal("5000")),  # "value today" overwrite
            ),
            monthly_contribution=Decimal("0"), growth_pct=Decimal("0"),
        )
        series = project_holding(h, TODAY, months=6)
        assert {v for _, v in series.forecast} == {Decimal("5000.00")}

    def test_a_future_dated_valuation_is_not_the_value_today(self):
        h = _isa(
            valuations=((date(2025, 6, 1), Decimal("800")), (date(2026, 3, 1), Decimal("9999"))),
            monthly_contribution=Decimal("0"), growth_pct=Decimal("0"),
        )
        assert project_holding(h, TODAY, months=1).forecast[0][1] == Decimal("800.00")

    def test_overwriting_value_today_changes_the_forecast_from_today(self):
        before = _isa(valuations=((date(2025, 1, 1), Decimal("1000")),))
        after = _isa(valuations=((date(2025, 1, 1), Decimal("1000")), (TODAY, Decimal("3000"))))
        b = project_holding(before, TODAY, months=12).forecast
        a = project_holding(after, TODAY, months=12).forecast
        assert a[0][1] - b[0][1] == Decimal("2000.00")
        # The £2,000 difference itself grows at 7% over the year.
        assert a[12][1] - b[12][1] == Decimal("2140.00")


class TestLinkedContributionsPaidSinceTheValuation:
    """A linked contribution that has left the bank is in the holding, so net
    worth doesn't drop on the payment day (ADR-002, T-11-3)."""

    def _linked(self, paid):
        return _isa(
            valuations=((date(2025, 12, 1), Decimal("5000")),),
            growth_pct=Decimal("0"), monthly_contribution=Decimal("1000"),
            paid_contributions=paid,
        )

    def test_payments_after_the_latest_valuation_add_to_value_today(self):
        h = self._linked(((date(2025, 12, 10), Decimal("1000")), (date(2026, 1, 10), Decimal("1000"))))
        assert project_holding(h, TODAY, months=1).forecast[0][1] == Decimal("7000.00")

    def test_a_payment_on_or_before_the_valuation_day_is_already_inside_it(self):
        h = self._linked(((date(2025, 11, 10), Decimal("1000")), (date(2025, 12, 1), Decimal("1000"))))
        assert project_holding(h, TODAY, months=1).forecast[0][1] == Decimal("5000.00")

    def test_a_new_valuation_rebases_and_absorbs_earlier_payments(self):
        h = _isa(
            valuations=((date(2025, 12, 1), Decimal("5000")), (date(2026, 1, 12), Decimal("6100"))),
            growth_pct=Decimal("0"), monthly_contribution=Decimal("0"),
            paid_contributions=((date(2025, 12, 10), Decimal("1000")),),
        )
        assert project_holding(h, TODAY, months=1).forecast[0][1] == Decimal("6100.00")

    def test_only_payments_within_90_days_of_the_valuation_count(self):
        """sec, ADR-002: an unconfirmed stream of payments can't inflate a
        holding for ever; after 90 days the user re-values it."""
        h = self._linked((
            (date(2025, 12, 1) + timedelta(days=90), Decimal("1000")),
            (date(2025, 12, 1) + timedelta(days=91), Decimal("1000")),
        ))
        later = date(2026, 4, 1)
        assert value_on(h, later) == Decimal("6000")

    def test_the_90_day_window_follows_the_valuation_in_effect_at_each_point(self):
        h = _isa(
            valuations=((date(2025, 1, 1), Decimal("100")), (date(2025, 6, 1), Decimal("500"))),
            paid_contributions=((date(2025, 5, 1), Decimal("50")), (date(2025, 6, 20), Decimal("50"))),
        )
        assert value_on(h, date(2025, 5, 15)) == Decimal("100")  # 120 days after the first valuation
        assert value_on(h, date(2025, 6, 30)) == Decimal("550")

    def test_history_points_count_payments_up_to_that_point(self):
        h = self._linked(((date(2025, 12, 10), Decimal("1000")),))
        points = [date(2025, 11, 30), date(2025, 12, 5), date(2025, 12, 31)]
        series = project_holding(h, TODAY, months=1, history_points=points)
        assert series.history == [
            (date(2025, 11, 30), None),
            (date(2025, 12, 5), Decimal("5000.00")),
            (date(2025, 12, 31), Decimal("6000.00")),
        ]


class TestHistory:
    def test_history_is_the_latest_valuation_on_or_before_each_point(self):
        h = _isa(valuations=(
            (date(2025, 10, 10), Decimal("100")),
            (date(2025, 12, 5), Decimal("300")),
        ))
        points = [date(2025, 9, 30), date(2025, 10, 31), date(2025, 11, 30), date(2025, 12, 31)]
        series = project_holding(h, TODAY, months=1, history_points=points)
        assert series.history == [
            (date(2025, 9, 30), None),  # not tracked yet: no point, not £0
            (date(2025, 10, 31), Decimal("100.00")),
            (date(2025, 11, 30), Decimal("100.00")),
            (date(2025, 12, 31), Decimal("300.00")),
        ]


class TestDebtsAndOtherModels:
    def test_a_legacy_asset_liability_pays_down_and_stops_at_zero(self):
        loan = HoldingInput(
            id="l", name="Old loan", kind="loan", model="growth",
            valuations=((TODAY, Decimal("-250")),), growth_pct=Decimal("0"),
            monthly_contribution=Decimal("100"), is_debt=True,
        )
        values = [v for _, v in project_holding(loan, TODAY, months=4).forecast]
        assert values == [Decimal("-250.00"), Decimal("-150.00"), Decimal("-50.00"), Decimal("0.00"), Decimal("0.00")]

    def test_an_amortising_holding_follows_the_schedule_it_is_given(self):
        owed = {TODAY: Decimal("900"), date(2026, 2, 15): Decimal("600"), date(2026, 3, 15): Decimal("300")}
        loan = HoldingInput(
            id="l2", name="Car loan", kind="loan", model="amortisation",
            valuations=(), is_debt=True, owed_on=lambda d: owed[d],
        )
        values = [v for _, v in project_holding(loan, TODAY, months=2).forecast]
        assert values == [Decimal("-900.00"), Decimal("-600.00"), Decimal("-300.00")]

    def test_an_unknown_model_holds_the_stored_value_flat_and_is_never_dropped(self):
        odd = _isa(model="something_new", valuations=((TODAY, Decimal("4321")),))
        values = {v for _, v in project_holding(odd, TODAY, months=24).forecast}
        assert values == {Decimal("4321.00")}

    def test_a_holding_with_no_value_yet_contributes_nothing(self):
        series = project_holding(_isa(valuations=()), TODAY, months=3)
        assert series.forecast == []


class TestTotals:
    def _three(self):
        return [
            _isa(id="a", valuations=((TODAY, Decimal("1000")),)),
            _isa(id="b", kind="pension", valuations=((TODAY, Decimal("5000")),), monthly_contribution=Decimal("0")),
            HoldingInput(id="c", name="House", kind="property", model="growth",
                         valuations=((TODAY, Decimal("200000")),), growth_pct=Decimal("2")),
        ]

    def test_the_total_is_the_sum_of_the_holdings_on_every_date(self):
        p = project_holdings(self._three(), TODAY, months=36)
        for i, (when, total) in enumerate(p.total):
            shown = sum(s.forecast[i][1] for s in p.per_holding)
            # Rounded once from the exact values: within a penny per holding
            # of the sum of the rounded figures, never further.
            assert abs(total - shown) <= Decimal("0.01") * len(p.per_holding)
            assert all(s.forecast[i][0] == when for s in p.per_holding)

    def test_the_total_is_rounded_once_not_summed_from_rounded_parts(self):
        thirds = [HoldingInput(id=str(i), name="x", kind="other", model="flat",
                               valuations=((TODAY, Decimal("0.004")),)) for i in range(3)]
        p = project_holdings(thirds, TODAY, months=0)
        assert [s.forecast[0][1] for s in p.per_holding] == [Decimal("0.00")] * 3
        assert p.total[0][1] == Decimal("0.01")

    def test_holdings_with_no_value_are_left_out_of_the_total(self):
        p = project_holdings(self._three() + [_isa(id="d", valuations=())], TODAY, months=2)
        assert [s.id for s in p.per_holding] == ["a", "b", "c"]

    def test_no_holdings_gives_an_empty_total(self):
        assert project_holdings([], TODAY, months=12).total == []


class TestBounds:
    def test_the_largest_inputs_stay_finite_and_fast(self):
        import time
        h = _isa(valuations=((TODAY, Decimal("10000000")),), growth_pct=Decimal("50"),
                 monthly_contribution=Decimal("10000000"))
        start = time.perf_counter()
        # 100 holdings is the per-user cap (ADR-002 section 6).
        p = project_holdings([h] * 100, TODAY, months=600)
        assert time.perf_counter() - start < 1
        assert p.total[-1][1].is_finite()

    def test_minus_one_hundred_percent_wipes_the_value_within_a_month(self):
        h = _isa(valuations=((TODAY, Decimal("1000")),), growth_pct=Decimal("-100"),
                 monthly_contribution=Decimal("0"))
        assert project_holding(h, TODAY, months=1).forecast[1][1] == Decimal("0.00")

    @pytest.mark.parametrize("pct", ["-100.01", "50.01"])
    def test_a_growth_rate_outside_minus_100_to_50_is_refused_not_clamped(self, pct):
        with pytest.raises(ValueError):
            project_holding(_isa(growth_pct=Decimal(pct)), TODAY, months=12)

    @pytest.mark.parametrize("months", [-1, 601])
    def test_a_horizon_outside_0_to_600_months_is_refused(self, months):
        with pytest.raises(ValueError):
            project_holding(_isa(), TODAY, months=months)
