"""Net worth subtracts liabilities on every surface (T-10-7b; sec S-6, S-7).

One shared total (`net_worth.liabilities_total`) feeds the summary (which is
what Claude's `cashflow_summary` reads) and the reconstructed series behind
net worth position, history and projection. A liability counts from its
as-of date, like an asset valuation. Nothing else moves: safe-to-spend, the
forecast and the asset decomposition stay as they were (the repayment
reaches the forecast through the commitment link, T-10-8).

A `loan` asset the user already typed in is converted only by the asset id
the user picked, in one transaction (create the liability, delete the asset).
Until then both count: that overstates debt, the safe side, and is never a
silent drop.

Synthetic fixture (public repo): a £9,000 loan at £200 a month, 11% APR.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core import user_crypto
from app.models import Asset, AssetValuation, CommitmentRule, Liability, User
from tests.clock import TODAY
from tests.integration.test_oauth import READ, _bearer, _connect, _web_login
from tests.integration.test_transactions_endpoint import _account, _dek_from_token

API = "/api/v1"
AS_OF = TODAY - timedelta(days=5)
LOAN = {
    "kind": "loan", "lender": "Example Bank", "balance": "9000.00", "balance_as_of": AS_OF.isoformat(),
    "apr": "11.00", "payment": "200.00", "start_date": (TODAY + timedelta(days=10)).isoformat(),
}


class World:
    def __init__(self, client, db, email="nw@example.com", token=None):
        self.client, self.db = client, db
        self.web = token or _web_login(client, email)
        self.dek = _dek_from_token(self.web)
        self.user = db.query(User).filter(User.email == email).one()

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def bank(self):
        def make():
            _account(self.db, self.user.id, name="Current", balance="3000")
            self.db.add(CommitmentRule(
                user_id=self.user.id, direction="income", label="Salary", amount=Decimal("2500"),
                cadence="monthly", next_date=TODAY + timedelta(days=12), source="manual",
                status="confirmed", is_payday=True,
            ))
            self.db.commit()
        self.as_user(make)

    def loan_asset(self, name="Car loan", value="-9000", asset_type="loan"):
        def make():
            asset = Asset(user_id=self.user.id, name=name, asset_type=asset_type)
            self.db.add(asset)
            self.db.flush()
            self.db.add(AssetValuation(asset_id=asset.id, value=Decimal(value), valued_at=AS_OF))
            self.db.commit()
            return str(asset.id)
        return self.as_user(make)

    def get(self, path, token=None):
        res = self.client.get(f"{API}{path}", headers=_bearer(token or self.web))
        assert res.status_code == 200, (path, res.text)
        return res.json()

    def add_liability(self, **overrides):
        return self.client.post(f"{API}/liabilities", json={**LOAN, **overrides}, headers=_bearer(self.web))

    def figures(self) -> dict:
        """Every surface that carries net worth, and the ones that must not move."""
        summary = self.get("/analytics/summary")
        position = self.get("/analytics/net-worth-position")
        history = self.get("/analytics/net-worth-history?months=2")
        projection = self.get("/analytics/net-worth-projection")
        forecast = self.get("/analytics/forecast")
        return {
            "summary": Decimal(summary["net_worth"]),
            "position": Decimal(position["net_worth"]),
            # Oldest first: two month-ends back, then last month-end, then today.
            "history_today": Decimal(history[-1]["net_worth"]),
            "history_before_as_of": Decimal(history[0]["net_worth"]),
            "projection_now": Decimal(projection["current_net_worth"]),
            "projection_next_month": Decimal(projection["timeline"][1]["value"]),
            "safe_to_spend": Decimal(summary["safe_to_spend"]),
            "forecast": [(p["date"], p["balance"]) for p in forecast["timeline"]],
            "decomposition": self.get("/analytics/net-worth-decomposition"),
        }


@pytest.fixture
def world(client, db_session):
    w = World(client, db_session)
    w.bank()
    return w


def _liabilities(db) -> int:
    return db.execute(select(func.count()).select_from(Liability)).scalar()


# --------------------------------------------------------------------------- #
# Every surface (S-6)
# --------------------------------------------------------------------------- #
def test_net_worth_subtracts_liability_balance(world):
    before = world.figures()
    assert world.add_liability().status_code == 201
    after = world.figures()

    for surface in ("summary", "position", "history_today", "projection_now", "projection_next_month"):
        assert after[surface] == before[surface] - Decimal("9000.00"), surface


def test_the_liability_counts_from_its_as_of_date_like_a_valuation(world):
    before = world.figures()
    world.add_liability()
    # The history's oldest point (two month-ends back) is before the as-of date.
    assert world.figures()["history_before_as_of"] == before["history_before_as_of"]


def test_nothing_but_net_worth_moves(world):
    before = world.figures()
    world.add_liability()
    after = world.figures()
    for unmoved in ("safe_to_spend", "forecast", "decomposition"):
        assert after[unmoved] == before[unmoved], unmoved


def test_summary_and_position_report_the_same_liabilities_total(world):
    world.add_liability()
    world.add_liability(lender="Second", balance="1500.00", payment="100.00", kind="finance")
    summary = world.get("/analytics/summary")
    position = world.get("/analytics/net-worth-position")
    assert Decimal(summary["liabilities_total"]) == Decimal("10500.00")
    assert Decimal(position["liabilities"]) == Decimal("10500.00")
    history = world.get("/analytics/net-worth-history?months=1")
    assert Decimal(history[-1]["liabilities"]) == Decimal("10500.00")


def test_a_liability_repaid_irregularly_still_counts(world):
    before = world.figures()["summary"]
    world.add_liability(payment=None, opted_out=True)
    assert world.figures()["summary"] == before - Decimal("9000.00")


def test_projection_keeps_the_debt_flat_until_payments_are_linked(world):
    # Until T-10-8 links the repayment, nothing says the £200 leaves the bank
    # in the forecast, so the projection doesn't pay the debt down either.
    world.add_liability()
    timeline = world.get("/analytics/net-worth-projection")["timeline"]
    assert [Decimal(timeline[m]["assets"]) for m in (0, 1, 6)] == [Decimal("-9000.00")] * 3


def test_claude_sees_liabilities_only_inside_the_summary_net_worth(client, db_session):
    web, _, tokens = _connect(client, scopes=(READ,), email="claude-nw@example.com")
    w = World(client, db_session, email="claude-nw@example.com", token=web)
    w.bank()
    before = Decimal(w.get("/analytics/summary", token=tokens["access_token"])["net_worth"])
    w.add_liability()
    after = w.get("/analytics/summary", token=tokens["access_token"])
    assert Decimal(after["net_worth"]) == before - Decimal("9000.00")
    assert client.get(f"{API}/liabilities", headers=_bearer(tokens["access_token"])).status_code == 401


# --------------------------------------------------------------------------- #
# Converting a loan asset (no silent double count)
# --------------------------------------------------------------------------- #
def test_a_loan_asset_and_a_liability_both_count_until_converted(world):
    world.loan_asset()
    before = world.figures()["summary"]
    world.add_liability()
    assert world.figures()["summary"] == before - Decimal("9000.00")


def test_converting_the_picked_asset_counts_the_debt_once(world, db_session):
    asset_id = world.loan_asset()
    before = world.figures()["summary"]

    res = world.add_liability(replaces_asset_id=asset_id)
    assert res.status_code == 201, res.text
    assert world.figures()["summary"] == before  # −£9,000 asset swapped for a £9,000 liability
    assert db_session.query(Asset).count() == 0
    assert _liabilities(db_session) == 1


def test_an_other_liability_asset_can_be_converted(world, db_session):
    asset_id = world.loan_asset(name="Sofa finance", value="-1500", asset_type="other_liability")
    res = world.add_liability(replaces_asset_id=asset_id, kind="finance", balance="1500.00", payment="100.00")
    assert res.status_code == 201, res.text
    assert db_session.query(Asset).count() == 0


def test_converting_twice_gives_404_and_no_second_liability(world, db_session):
    asset_id = world.loan_asset()
    assert world.add_liability(replaces_asset_id=asset_id).status_code == 201
    again = world.add_liability(replaces_asset_id=asset_id)
    assert again.status_code == 404
    assert _liabilities(db_session) == 1


def test_another_users_asset_is_a_404_and_nothing_is_written(world, client, db_session):
    bob = World(client, db_session, email="bob-nw@example.com")
    theirs = bob.loan_asset()
    unknown = "00000000-0000-0000-0000-0000000000aa"
    for asset_id in (theirs, unknown):
        res = world.add_liability(replaces_asset_id=asset_id)
        assert res.status_code == 404
        assert res.json() == {"detail": "Asset not found"}
    assert _liabilities(db_session) == 0
    assert db_session.query(Asset).count() == 1  # Bob's asset is untouched


@pytest.mark.parametrize("asset_type", ["isa", "property", "mortgage"])
def test_only_loan_type_assets_can_be_converted(world, db_session, asset_type):
    asset_id = world.loan_asset(asset_type=asset_type)
    assert world.add_liability(replaces_asset_id=asset_id).status_code == 422
    assert _liabilities(db_session) == 0
    assert db_session.query(Asset).count() == 1


def test_a_refused_liability_keeps_the_asset(world, db_session):
    asset_id = world.loan_asset()
    assert world.add_liability(replaces_asset_id=asset_id, payment="10.00").status_code == 422
    assert _liabilities(db_session) == 0
    assert db_session.query(Asset).count() == 1


def test_an_edit_cannot_convert_an_asset(world):
    asset_id = world.loan_asset()
    created = world.add_liability().json()
    res = world.client.patch(f"{API}/liabilities/{created['id']}", json={"replaces_asset_id": asset_id},
                             headers=_bearer(world.web))
    assert res.status_code == 422
