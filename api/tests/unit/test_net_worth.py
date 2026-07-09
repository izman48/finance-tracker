"""Unit tests for manual assets and net-worth history reconstruction."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models import Account, Asset, AssetFlow, AssetValuation, Transaction, User
from app.models import CommitmentRule
from app.models.commitment_rule import CommitmentStatus
from app.services import analytics_service as svc


def _user(db):
    u = User(email=f"nw-{datetime.now().timestamp()}@example.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _account(db, user, balance, atype="TRANSACTION", name="Main"):
    a = Account(
        user_id=user.id,
        bank_connection_id=user.id,  # FK not enforced in sqlite test
        external_id=f"ext-{name}-{datetime.now().timestamp()}",
        provider_name="Test",
        account_type=atype,
        display_name=name,
        current_balance=Decimal(balance),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _tx(db, account, amount, when, ttype="debit"):
    t = Transaction(
        account_id=account.id,
        external_id=f"tx-{account.id}-{when.isoformat()}-{ttype}-{amount}",
        transaction_type=ttype,
        amount=Decimal(str(amount)),
        currency="GBP",
        description="t",
        merchant_name="t",
        transaction_date=datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc),
    )
    db.add(t)
    db.commit()
    return t


def _asset(db, user, name, values: dict[date, str]):
    a = Asset(user_id=user.id, name=name, asset_type="isa")
    db.add(a)
    db.flush()
    for valued_at, value in values.items():
        db.add(AssetValuation(asset_id=a.id, value=Decimal(value), valued_at=valued_at))
    db.commit()
    return a


class TestAssetsTotal:
    def test_latest_valuation_wins(self, db_session):
        user = _user(db_session)
        _asset(db_session, user, "S&S ISA", {
            date.today() - timedelta(days=60): "5000",
            date.today(): "6000",
        })
        assert svc.assets_total(db_session, user) == Decimal("6000")

    def test_as_of_uses_step_function(self, db_session):
        user = _user(db_session)
        _asset(db_session, user, "S&S ISA", {
            date.today() - timedelta(days=60): "5000",
            date.today(): "6000",
        })
        as_of = date.today() - timedelta(days=30)
        assert svc.assets_total(db_session, user, as_of=as_of) == Decimal("5000")

    def test_before_first_valuation_counts_zero(self, db_session):
        user = _user(db_session)
        _asset(db_session, user, "S&S ISA", {date.today(): "6000"})
        assert svc.assets_total(db_session, user, as_of=date.today() - timedelta(days=10)) == Decimal("0")

    def test_liability_negative_valuation_subtracts(self, db_session):
        """A liability is stored as a negative valuation and reduces the total."""
        user = _user(db_session)
        _asset(db_session, user, "S&S ISA", {date.today(): "6000"})
        loan = Asset(user_id=user.id, name="Car loan", asset_type="loan")
        db_session.add(loan)
        db_session.flush()
        db_session.add(AssetValuation(asset_id=loan.id, value=Decimal("-6800"), valued_at=date.today()))
        db_session.commit()
        assert svc.assets_total(db_session, user) == Decimal("-800")  # 6000 − 6800


class TestAssetDecomposition:
    def _flow(self, db, asset, amount, when):
        f = AssetFlow(asset_id=asset.id, amount=Decimal(str(amount)), flow_date=when)
        db.add(f)
        db.commit()
        return f

    def test_growth_is_delta_minus_flows(self, db_session):
        user = _user(db_session)
        today = svc._today()
        a = _asset(db_session, user, "ISA", {
            today - timedelta(days=200): "5000",
            today: "7000",
        })
        self._flow(db_session, a, 1500, today - timedelta(days=90))
        d = svc.asset_decomposition(db_session, user, months=6)
        assert d["assets_delta"] == Decimal("2000")
        assert d["contributions"] == Decimal("1500")
        assert d["growth"] == Decimal("500")
        assert d["flows_recorded"] == 1

    def test_flows_outside_the_window_are_ignored(self, db_session):
        user = _user(db_session)
        today = svc._today()
        a = _asset(db_session, user, "ISA", {today: "7000"})
        self._flow(db_session, a, 9999, today - timedelta(days=400))  # before window
        d = svc.asset_decomposition(db_session, user, months=6)
        assert d["contributions"] == Decimal("0")
        assert d["flows_recorded"] == 0

    def test_withdrawals_subtract_from_contributions(self, db_session):
        user = _user(db_session)
        today = svc._today()
        a = _asset(db_session, user, "ISA", {
            today - timedelta(days=100): "10000",
            today: "9500",
        })
        self._flow(db_session, a, -1000, today - timedelta(days=30))  # took £1k out
        d = svc.asset_decomposition(db_session, user, months=6)
        # Fell £500 despite a £1,000 withdrawal -> £500 of growth.
        assert d["assets_delta"] == Decimal("-500")
        assert d["contributions"] == Decimal("-1000")
        assert d["growth"] == Decimal("500")

    def test_scoped_to_the_user(self, db_session):
        user, other = _user(db_session), _user(db_session)
        today = svc._today()
        theirs = _asset(db_session, other, "Their ISA", {today: "5000"})
        self._flow(db_session, theirs, 5000, today - timedelta(days=10))
        d = svc.asset_decomposition(db_session, user, months=6)
        assert d["contributions"] == Decimal("0")
        assert d["flows_recorded"] == 0


class TestDerivedContribution:
    def _commit(self, db, user, direction, amount, cadence="monthly"):
        r = CommitmentRule(
            user_id=user.id, direction=direction, label=f"{direction}-{amount}",
            amount=Decimal(str(amount)), cadence=cadence,
            next_date=svc._today() + timedelta(days=7),
            status=CommitmentStatus.CONFIRMED.value,
        )
        db.add(r)
        db.commit()
        return r

    def test_income_minus_bills_minus_avg_spending(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user, 1000)
        self._commit(db_session, user, "income", 3200)
        self._commit(db_session, user, "expense", 1100)
        # Everyday spending: £600 in each of the last two complete months.
        today = svc._today()
        last_m = date(today.year, today.month, 1) - timedelta(days=1)
        prev_m = date(last_m.year, last_m.month, 1) - timedelta(days=1)
        _tx(db_session, acc, 600, last_m.replace(day=10), ttype="debit")
        _tx(db_session, acc, 600, prev_m.replace(day=10), ttype="debit")

        d = svc.derived_contribution(db_session, user)
        assert d["income_monthly"] == Decimal("3200.00")
        assert d["bills_monthly"] == Decimal("1100.00")
        # £1,200 over the sampled complete months, averaged over the window.
        assert d["avg_spending_monthly"] > 0
        assert d["contribution"] == d["income_monthly"] - d["bills_monthly"] - d["avg_spending_monthly"]

    def test_current_partial_month_is_excluded_from_the_average(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user, 1000)
        # Big spend TODAY (partial month) must not drag the average.
        _tx(db_session, acc, 5000, svc._today(), ttype="debit")
        d = svc.derived_contribution(db_session, user)
        assert d["avg_spending_monthly"] == Decimal("0.00")

    def test_projection_derives_when_no_contribution_given(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 1000)
        self._commit(db_session, user, "income", 2000)
        self._commit(db_session, user, "expense", 500)
        p = svc.net_worth_projection(db_session, user, annual_growth_pct=Decimal("0"))
        assert p["contribution_basis"] is not None
        assert p["monthly_contribution"] == Decimal("1500.00")
        # month 1 = 1000 + 1500
        assert p["timeline"][1]["value"] == Decimal("2500.00")

    def test_custom_contribution_skips_derivation_and_allows_negative(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 1000)
        p = svc.net_worth_projection(
            db_session, user,
            monthly_contribution=Decimal("-100"),
            annual_growth_pct=Decimal("0"),
        )
        assert p["contribution_basis"] is None
        assert p["timeline"][1]["value"] == Decimal("900.00")  # drawdown honoured


class TestNetWorthProjection:
    def test_zero_growth_is_linear_contributions(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 1000)
        p = svc.net_worth_projection(
            db_session, user,
            target_amount=Decimal("2200"),
            monthly_contribution=Decimal("100"),
            annual_growth_pct=Decimal("0"),
        )
        assert p["current_net_worth"] == Decimal("1000.00")
        # 1000 + 100/mo, no growth -> hits 2200 at month 12 exactly
        assert p["target_date"] == svc._add_months(svc._today(), 12)
        assert p["timeline"][0]["value"] == Decimal("1000.00")
        assert p["timeline"][1]["value"] == Decimal("1100.00")

    def test_bank_cash_is_held_flat_but_assets_compound(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 10000)  # bank buffer: must NOT compound
        _asset(db_session, user, "ISA", {date.today() - timedelta(days=1): "10000"})
        p = svc.net_worth_projection(
            db_session, user, annual_growth_pct=Decimal("5"),
        )
        year_on = [pt for pt in p["timeline"] if pt["date"] == svc._add_months(svc._today(), 12)]
        # Bank stays 10000; the asset compounds to ~10500 → total ~20500.
        assert year_on and abs(year_on[0]["value"] - Decimal("20500")) < Decimal("2")
        assert p["bank_component"] == Decimal("10000.00")

    def test_per_asset_growth_override_and_flat_liability(self, db_session):
        user = _user(db_session)
        yesterday = date.today() - timedelta(days=1)
        fast = _asset(db_session, user, "Crypto", {yesterday: "1000"})
        fast.assumed_growth_pct = Decimal("12")
        loan = Asset(user_id=user.id, name="Car loan", asset_type="loan")
        db_session.add(loan)
        db_session.flush()
        db_session.add(AssetValuation(asset_id=loan.id, value=Decimal("-5000"), valued_at=yesterday))
        db_session.commit()

        p = svc.net_worth_projection(db_session, user, annual_growth_pct=Decimal("0"))
        year_on = [pt for pt in p["timeline"] if pt["date"] == svc._add_months(svc._today(), 12)]
        # Crypto at 12% → ~1120; the loan (no override) held flat at −5000.
        assert year_on and abs(year_on[0]["value"] - Decimal("-3880")) < Decimal("2")
        by_name = {a["name"]: a["growth_pct"] for a in p["asset_assumptions"]}
        assert by_name["Crypto"] == Decimal("12")
        assert by_name["Car loan"] == Decimal("0")

    def test_surplus_occurrence_later_this_month_lands_in_month_one(self, db_session):
        user = _user(db_session)
        db_session.add(CommitmentRule(
            user_id=user.id, direction="income", label="Pay", amount=Decimal("1000"),
            cadence="monthly", next_date=svc._today() + timedelta(days=5),
            status=CommitmentStatus.CONFIRMED.value,
        ))
        db_session.commit()
        series = svc.monthly_surplus_series(db_session, user, 3, Decimal("0"))
        # One occurrence per month-window, starting with the one 5 days out.
        assert series == [Decimal("1000"), Decimal("1000"), Decimal("1000")]

    def test_target_already_reached_is_today(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 5000)
        p = svc.net_worth_projection(
            db_session, user,
            target_amount=Decimal("4000"),
            monthly_contribution=Decimal("0"),
            annual_growth_pct=Decimal("-10"),  # shrinking — month 1 check would miss it
        )
        assert p["target_date"] == svc._today()

    def test_unreachable_target_returns_none(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 100)
        p = svc.net_worth_projection(
            db_session, user,
            target_amount=Decimal("100000000"),
            monthly_contribution=Decimal("10"),
            annual_growth_pct=Decimal("0"),
        )
        assert p["target_date"] is None
        # And the chart payload stays bounded (MAX_MONTHS + the today point).
        assert len(p["timeline"]) <= 601


class TestNetWorthHistory:
    def test_bank_balance_reconstruction(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user, 1000)
        # Recent activity: spent 100, received 200 (both inside this month).
        _tx(db_session, acc, 100, date.today() - timedelta(days=1), ttype="debit")
        _tx(db_session, acc, 200, date.today() - timedelta(days=2), ttype="credit")

        history = svc.net_worth_history(db_session, user, months=1)
        today_point = history[-1]
        month_end = history[0]

        assert today_point["net_worth"] == Decimal("1000")
        # Before both transactions: 1000 - (200 - 100) = 900
        assert month_end["net_worth"] == Decimal("900")

    def test_credit_account_subtracts_owed(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 1000, name="Cur")
        card = _account(db_session, user, 250, atype="CREDIT_CARD", name="Card")
        # Spent 50 on the card yesterday: owed before = 200.
        _tx(db_session, card, 50, date.today() - timedelta(days=1), ttype="debit")

        history = svc.net_worth_history(db_session, user, months=1)
        assert history[-1]["net_worth"] == Decimal("750")  # 1000 - 250
        assert history[0]["net_worth"] == Decimal("800")  # 1000 - 200

    def test_assets_included_stepwise(self, db_session):
        user = _user(db_session)
        _account(db_session, user, 100)
        # Use the code's own "today" (UTC) so the newest valuation is dated on
        # the same day the history's final point is computed for — otherwise a
        # local/UTC date-boundary drops it and the assertion flakes.
        today = svc._today()
        _asset(db_session, user, "ISA", {
            today - timedelta(days=400): "5000",
            today: "7000",
        })
        history = svc.net_worth_history(db_session, user, months=2)
        assert history[-1]["net_worth"] == Decimal("7100")
        assert history[0]["net_worth"] == Decimal("5100")
