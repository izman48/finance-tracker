"""Holdings read from storage, and the target projection using the engine
(T-11-4, ADR-002).

`holding_inputs` adapts the existing `assets` and `liabilities` rows (read in
the request with the user's key) into engine inputs, keeping today's rules:
an asset grows at its own % or the projection's default (a legacy
asset-liability at 0%), adds its monthly contribution, and a liability
follows its loan schedule when linked or stays flat when not. The target
projection's assets and liabilities on every month are exactly the engine's
totals (the equality test the sprint asks for).

Synthetic figures only.
"""
from datetime import timedelta
from decimal import Decimal

from app.models import Asset, AssetValuation, CommitmentRule, Liability
from app.services import analytics_service as svc
from app.services.holdings.inputs import holding_inputs
from app.services.holdings.projection import project_holdings, total_at
from tests.unit.test_net_worth import _account, _user


def _asset(db, user, name, typ, value, pct=None, contribution=None, days_ago=10):
    a = Asset(user_id=user.id, name=name, asset_type=typ, assumed_growth_pct=pct,
              monthly_contribution=contribution)
    db.add(a)
    db.flush()
    db.add(AssetValuation(asset_id=a.id, value=Decimal(value), valued_at=svc._today() - timedelta(days=days_ago)))
    db.commit()
    return a


def _world(db):
    user = _user(db)
    today = svc._today()
    _account(db, user, 2000)
    rule = CommitmentRule(user_id=user.id, direction="expense", label="Loan", amount=Decimal("120"),
                          cadence="monthly", next_date=today + timedelta(days=6), status="confirmed")
    db.add(rule)
    db.flush()
    _asset(db, user, "ISA", "isa", "4000", pct=Decimal("6"), contribution=Decimal("200"))
    _asset(db, user, "Pension", "pension", "9000")
    _asset(db, user, "Flat", "property", "150000", pct=Decimal("3"))
    _asset(db, user, "Old loan", "loan", "-900", contribution=Decimal("100"))
    db.add(Liability(user_id=user.id, kind="loan", lender="Lender A", balance=Decimal("3000"),
                     balance_as_of=today - timedelta(days=4), apr=Decimal("8"), payment=Decimal("120"),
                     start_date=today - timedelta(days=30), linked_commitment_id=rule.id))
    db.add(Liability(user_id=user.id, kind="loan", lender="Lender B", balance=Decimal("500"),
                     balance_as_of=today - timedelta(days=2), apr=Decimal("0"), payment=Decimal("50"),
                     start_date=today + timedelta(days=3)))
    db.commit()
    return user


class TestHoldingInputs:
    def test_assets_keep_their_growth_rules_and_contribution(self, db_session):
        user = _world(db_session)
        by_name = {h.name: h for h in holding_inputs(db_session, user, svc._today(), Decimal("5"))}
        assert by_name["ISA"].growth_pct == Decimal("6")
        assert by_name["ISA"].monthly_contribution == Decimal("200")
        assert by_name["Pension"].growth_pct == Decimal("5")  # the projection's default
        assert by_name["Old loan"].growth_pct == Decimal("0") and by_name["Old loan"].is_debt
        assert {h.source for h in by_name.values() if h.kind == "loan" and h.name != "Old loan"} == {"liabilities"}

    def test_a_liability_is_owed_per_its_schedule_only_when_linked(self, db_session):
        user = _world(db_session)
        today = svc._today()
        p = project_holdings(holding_inputs(db_session, user, today, Decimal("5")), today, months=3)
        by_name = {s.name: s for s in p.per_holding}
        linked = [v for _, v in by_name["Lender A"].forecast]
        unlinked = [v for _, v in by_name["Lender B"].forecast]
        assert linked[3] > linked[0]  # paid down (less negative)
        assert set(unlinked) == {Decimal("-500.00")}  # flat: nothing says it's paid

    def test_another_users_holdings_are_never_read(self, db_session):
        _world(db_session)
        other = _user(db_session)
        assert holding_inputs(db_session, other, svc._today(), Decimal("5")) == []


class TestTargetProjectionUsesTheEngine:
    def test_assets_and_liabilities_on_every_month_equal_the_engine_totals(self, db_session):
        user = _world(db_session)
        today = svc._today()
        p = svc.net_worth_projection(db_session, user, annual_growth_pct=Decimal("5"))
        engine = project_holdings(holding_inputs(db_session, user, today, Decimal("5")), today, months=600)
        months = len(p["timeline"]) - 1
        assert months >= 120
        for m in range(1, months + 1):
            assets = total_at([s for s in engine.per_holding if s.source == "assets"], m)
            owed = -total_at([s for s in engine.per_holding if s.source == "liabilities"], m)
            assert p["timeline"][m]["assets"] == assets, m
            assert p["timeline"][m]["liabilities"] == owed, m


class TestNetWorthTakesValueTodayFromTheEngine:
    """Every net worth surface (summary, position, history, the projection's
    month 0) reads assets through `assets_total`, which takes each holding's
    value from the engine's `value_on`, so a linked contribution paid since
    the last valuation is in net worth the day it leaves the bank."""

    def test_assets_total_includes_contributions_the_engine_counts(self, db_session, monkeypatch):
        from dataclasses import replace

        from app.services.analytics import net_worth

        user = _world(db_session)
        today = svc._today()
        real = net_worth.holding_inputs

        def with_a_paid_contribution(db, u, day, pct):
            return [
                replace(h, paid_contributions=((today, Decimal("200")),)) if h.name == "ISA" else h
                for h in real(db, u, day, pct)
            ]

        before = net_worth.assets_total(db_session, user, as_of=today)
        monkeypatch.setattr(net_worth, "holding_inputs", with_a_paid_contribution)
        assert net_worth.assets_total(db_session, user, as_of=today) - before == Decimal("200")
        assert net_worth.assets_total(db_session, user) - before == Decimal("200")

    def test_liabilities_rows_are_not_counted_as_assets(self, db_session):
        user = _world(db_session)
        # 4000 + 9000 + 150000 - 900; the two liabilities rows are separate.
        assert svc.assets_total(db_session, user) == Decimal("162100")


class TestKindsComeFromTheRegistry:
    def test_investment_kinds_are_flagged_and_grouped(self, db_session):
        user = _world(db_session)
        by_name = {h.name: h for h in holding_inputs(db_session, user, svc._today(), Decimal("5"))}
        assert {n for n, h in by_name.items() if h.is_investment} == {"ISA", "Pension"}
        assert by_name["Flat"].group == "property"
        assert {by_name[n].group for n in ("Old loan", "Lender A", "Lender B")} == {"debt"}

    def test_an_unknown_asset_type_is_held_flat_at_its_stored_value(self, db_session):
        user = _user(db_session)
        _asset(db_session, user, "Mystery", "not_a_type", "1234", pct=Decimal("20"), contribution=Decimal("50"))
        (h,) = holding_inputs(db_session, user, svc._today(), Decimal("5"))
        values = {v for _, v in project_holdings([h], svc._today(), months=24).per_holding[0].forecast}
        assert values == {Decimal("1234.00")} and not h.is_investment

    def test_an_unknown_liability_kind_still_counts_as_debt(self, db_session):
        user = _user(db_session)
        today = svc._today()
        db_session.add(Liability(user_id=user.id, kind="not_a_kind", lender="Lender C", balance=Decimal("700"),
                                 balance_as_of=today - timedelta(days=1), apr=Decimal("0"),
                                 payment=Decimal("70"), start_date=today + timedelta(days=5)))
        db_session.commit()
        (h,) = holding_inputs(db_session, user, today, Decimal("5"))
        assert h.is_debt and h.source == "liabilities" and h.group == "debt"
        assert project_holdings([h], today, months=1).total[0][1] == Decimal("-700.00")
