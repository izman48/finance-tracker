"""Recurring income that didn't arrive is flagged late, shown but never counted (T-08-10).

Fixture (anonymised): "Income A", GBP 1,000 a month, confirmed.

Late = the latest expected date (worked back from next_date, so sync rolling
next_date forward can't hide it) is more than GRACE_DAYS past and no credit
matched to that commitment has landed since a week before it. Internal
transfer legs never clear it. It stays flagged for one cadence window, until
the next expected date. A late payment adds nothing to the balance line,
safe-to-spend, savable or the Wealth projections; it is listed in the
forecast's `late_income` and flagged on the commitment.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import user_crypto
from app.models import CommitmentRule, User
from app.services import analytics_service as svc
from app.services.analytics.common import _add_months
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_transactions_endpoint import _account, _dek_from_token, _tx

API = "/api/v1"
TODAY = date.today()
KEY = "income:income a"


class World:
    def __init__(self, client, db, email="late@example.com"):
        self.client, self.db = client, db
        self.web, _, tokens = _connect(client, scopes=(READ,), email=email)
        self.mcp = tokens["access_token"]
        self.dek = _dek_from_token(self.web)
        self.user = db.query(User).filter(User.email == email).one()
        self.current = self.as_user(lambda: _account(db, self.user.id, name="Current", balance="500.00"))

    def as_user(self, fn):
        token = user_crypto.current_dek.set(self.dek)
        try:
            return fn()
        finally:
            user_crypto.current_dek.reset(token)

    def income(self, next_date, *, created_days_ago=120):
        def make():
            rule = CommitmentRule(
                user_id=self.user.id, direction="income", label="Income A", amount=Decimal("1000.00"),
                cadence="monthly", next_date=next_date, source="detected", status="confirmed",
                match_key=KEY,
            )
            self.db.add(rule)
            self.db.commit()
            return rule.id
        rule_id = self.as_user(make)
        self.db.execute(text("UPDATE commitment_rules SET created_at = :t WHERE id = :id"),
                        {"t": datetime.now(timezone.utc) - timedelta(days=created_days_ago), "id": rule_id.hex})
        self.db.commit()
        return rule_id

    def credit(self, on, merchant="Income A", account=None):
        acc = account or self.current
        return self.as_user(lambda: _tx(self.db, acc, "1000.00", on, ttype="credit", merchant=merchant))

    def commitments(self, token=None):
        res = self.client.get(f"{API}/analytics/commitments", headers=_bearer(token or self.web))
        assert res.status_code == 200, res.text
        return {c["label"]: c for c in res.json()}

    def forecast(self, token=None):
        res = self.client.get(f"{API}/analytics/forecast", params={"horizon": "30"},
                              headers=_bearer(token or self.web))
        assert res.status_code == 200, res.text
        return res.json()

    def summary(self):
        return self.client.get(f"{API}/analytics/summary", headers=_bearer(self.web)).json()

    def projection_basis(self):
        return self.as_user(lambda: svc.derived_contribution(self.db, self.user))


def test_missed_income_is_flagged_late_on_the_commitment_and_in_the_forecast(client, db_session):
    w = World(client, db_session)
    expected = TODAY - timedelta(days=10)
    w.income(expected)
    row = w.commitments()["Income A"]
    assert row["late"] is True and row["expected_date"] == expected.isoformat()
    assert w.forecast()["late_income"] == [
        {"label": "Income A", "amount": "1000.00", "expected_date": expected.isoformat(),
         "commitment_id": row["id"]}
    ]


def test_late_income_adds_nothing_anywhere(client, db_session):
    """Same user, same data, with and without the missed payment: every money
    figure is identical (only the late flags differ)."""
    expected = TODAY - timedelta(days=10)
    late = World(client, db_session, "late-a@example.com")
    late.income(expected)
    never = World(client, db_session, "late-b@example.com")
    never.income(_add_months(expected, 1))  # only the next payment; no missed one

    for key in ("safe_to_spend", "savable", "committed_before_payday", "available_cash"):
        assert late.summary()[key] == never.summary()[key], key
    a, b = late.forecast(), never.forecast()
    assert [p["balance"] for p in a["timeline"]] == [p["balance"] for p in b["timeline"]]
    assert late.projection_basis() == never.projection_basis()


def test_a_sync_rolling_next_date_forward_does_not_hide_it(client, db_session):
    w = World(client, db_session)
    expected = TODAY - timedelta(days=10)
    w.income(expected)
    w.commitments()  # runs sync_suggestions, which advances a past next_date
    rule = w.as_user(lambda: db_session.query(CommitmentRule).one())
    assert rule.next_date > TODAY  # the trap: next_date is in the future now
    assert w.commitments()["Income A"]["late"] is True
    assert w.forecast()["late_income"][0]["expected_date"] == expected.isoformat()


def test_the_matching_credit_clears_it(client, db_session):
    w = World(client, db_session)
    w.income(TODAY - timedelta(days=10))
    w.credit(TODAY - timedelta(days=1))
    assert w.commitments()["Income A"]["late"] is False
    assert w.forecast()["late_income"] == []


def test_a_credit_a_few_days_early_counts(client, db_session):
    w = World(client, db_session)
    w.income(TODAY - timedelta(days=10))
    w.credit(TODAY - timedelta(days=13))
    assert w.commitments()["Income A"]["late"] is False


def test_a_transfer_from_own_savings_never_clears_it(client, db_session):
    w = World(client, db_session)
    w.income(TODAY - timedelta(days=10))
    savings = w.as_user(lambda: _account(db_session, w.user.id, atype="SAVINGS", name="Savings", balance="5000"))
    w.as_user(lambda: _tx(db_session, savings, "1000.00", TODAY - timedelta(days=2), ttype="debit", merchant="Income A"))
    w.credit(TODAY - timedelta(days=2))  # paired leg: an internal transfer, not the income
    assert w.commitments()["Income A"]["late"] is True


def test_an_unrelated_credit_does_not_clear_it(client, db_session):
    w = World(client, db_session)
    w.income(TODAY - timedelta(days=10))
    w.credit(TODAY - timedelta(days=1), merchant="Refund Shop")
    assert w.commitments()["Income A"]["late"] is True


@pytest.mark.parametrize("days_ago,late", [(3, False), (4, True)])
def test_a_short_grace_before_it_is_late(client, db_session, days_ago, late):
    w = World(client, db_session)
    w.income(TODAY - timedelta(days=days_ago))
    assert w.commitments()["Income A"]["late"] is late


def test_only_the_latest_missed_payment_is_flagged(client, db_session):
    """Flagged for one cadence window: the payment before that isn't listed."""
    w = World(client, db_session)
    w.income(TODAY - timedelta(days=40))  # missed then, and missed again ~10 days ago
    items = w.forecast()["late_income"]
    assert len(items) == 1
    assert date.fromisoformat(items[0]["expected_date"]) > TODAY - timedelta(days=31)


def test_a_commitment_added_after_the_date_is_not_late(client, db_session):
    w = World(client, db_session)
    w.income(TODAY - timedelta(days=10), created_days_ago=2)
    assert w.commitments()["Income A"]["late"] is False


def test_expenses_are_never_late(client, db_session):
    w = World(client, db_session)
    def make():
        db_session.add(CommitmentRule(
            user_id=w.user.id, direction="expense", label="Rent", amount=Decimal("700"), cadence="monthly",
            next_date=TODAY - timedelta(days=10), source="manual", status="confirmed"))
        db_session.commit()
    w.as_user(make)
    assert w.commitments()["Rent"]["late"] is False


def test_the_mcp_read_outputs_carry_the_flag(client, db_session):
    w = World(client, db_session)
    w.income(TODAY - timedelta(days=10))
    assert w.commitments(token=w.mcp)["Income A"]["late"] is True
    assert len(w.forecast(token=w.mcp)["late_income"]) == 1


@pytest.mark.parametrize("amount,clears", [
    ("5.00", False),      # a stray small credit from the payer doesn't hide a missing GBP 1,000
    ("979.99", False),    # just outside max(GBP 1, 2%) = GBP 20
    ("980.00", True),
    ("1020.00", True),
])
def test_only_a_credit_near_the_expected_amount_clears_it(client, db_session, amount, clears):
    w = World(client, db_session)
    w.income(TODAY - timedelta(days=10))
    w.as_user(lambda: _tx(db_session, w.current, amount, TODAY - timedelta(days=1), ttype="credit", merchant="Income A"))
    assert w.commitments()["Income A"]["late"] is (not clears)
