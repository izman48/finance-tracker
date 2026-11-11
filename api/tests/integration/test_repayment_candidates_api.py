"""Claude's read of likely repayments (T-03-5 P8; PRD `list_repayment_candidates`,
AC-18 read, AC-21 read works).

POST /api/v1/repayments/candidates takes its hints in a JSON body, so a
payer's name never reaches an access log (as transaction search does). It
needs only `finance:read`, returns only the caller's own payments, and
validates its limits: a range of at most 366 days, `limit` 1 to 50, short
visible text. It is rate limited per user, as each call decrypts a window.
"""
from datetime import date, timedelta

import pytest

from app.core.rate_limit import LIMITS
from tests.clock import TODAY
from tests.integration.test_oauth import READ, _bearer
from tests.integration.test_repayment_writes_api import World as Base
from tests.integration.test_transactions_endpoint import _tx

URL = "/api/v1/repayments/candidates"


class World(Base):
    def __init__(self, client, db, email="cand@example.com", scopes=(READ,)):
        super().__init__(client, db, email=email, scopes=scopes)
        account = self.ledger.account
        self.pizza = self.ledger.as_user(lambda: _tx(db, account, "200.00", TODAY - timedelta(days=4),
                                                     merchant="Pizza Express", category="Eating out"))
        self.sam_now = self.ledger.as_user(lambda: _tx(db, account, "60.00", TODAY - timedelta(days=2),
                                                       ttype="credit", merchant="SAM SMITH"))

    def ask(self, token=None, **body):
        return self.client.post(URL, json=body, headers=_bearer(token or self.mcp))


@pytest.fixture
def w(client, db_session):
    return World(client, db_session)


def test_a_read_token_lists_the_users_candidates(w):
    r = w.ask(payer="smith")
    assert r.status_code == 200, r.text
    [c] = r.json()["candidates"]
    assert c["credit_id"] == str(w.ledger.as_user(lambda: w.sam_now.id))
    assert c["likely_spend"]["spend_id"] == str(w.ledger.as_user(lambda: w.pizza.id))
    assert c["date"] == (TODAY - timedelta(days=2)).isoformat()


def test_another_users_payments_never_appear(client, db_session):
    other = World(client, db_session, email="other@example.com")
    theirs = {str(other.ledger.as_user(lambda t=t: t.id)) for t in (other.sam, other.sam_now)}
    w = World(client, db_session)
    ids = {c["credit_id"] for c in w.ask(frm=(TODAY - timedelta(days=366)).isoformat()).json()["candidates"]}
    assert str(w.ledger.as_user(lambda: w.sam_now.id)) in ids and not ids & theirs


@pytest.mark.parametrize("body", [
    {"frm": "2026-01-01", "to": "2027-01-03"},              # more than 366 days
    {"frm": "2026-11-02", "to": "2026-11-01"},              # backwards
    {"limit": 0}, {"limit": 51},
    {"payer": "x" * 101}, {"about": "a‮b"},             # too long; hidden characters
    {"spend_date": "07/11/2026"}, {"unknown": True},
])
def test_limits_are_validated(w, body):
    assert w.ask(**body).status_code == 422


def test_it_is_rate_limited_per_user(w):
    events, _ = LIMITS["repayment-candidates"]
    for _ in range(events):
        assert w.ask().status_code == 200
    assert w.ask().status_code == 429


def test_a_web_session_can_read_it_too(w):
    assert w.ask(token=w.web, spend_date=date(2026, 11, 6).isoformat()).status_code == 200
