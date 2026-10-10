"""Which bank connections have gone stale (T-08-11).

`GET /banking/sync-status` (finance:read; behind MCP `sync_status`) reports,
per connection: last successful sync, consent status, a stale flag, and each
account's name and last balance update. It reads stored data only and never
calls TrueLayer. Unknown is never reported as fine: never synced, last
synced over 48 h ago, or consent known to have lapsed all mean stale, and
consent is "unknown" unless we know it lapsed (its expiry isn't stored; the
access-token expiry is not the consent expiry).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from app.core import user_crypto
from app.models import Account, BankConnection, User
from tests.integration.test_oauth import READ, _bearer, _connect
from tests.integration.test_transactions_endpoint import _dek_from_token

API = "/api/v1"
NOW = datetime.now(timezone.utc)

CONNECTION_KEYS = {"connection_id", "provider", "last_synced_at", "consent", "stale", "accounts"}
ACCOUNT_KEYS = {"display_name", "balance_updated_at"}


class World:
    def __init__(self, client, db, email="sync@example.com"):
        self.client, self.db = client, db
        self.web, _, tokens = _connect(client, scopes=(READ,), email=email)
        self.mcp = tokens["access_token"]
        self.dek = _dek_from_token(self.web)
        self.user = db.query(User).filter(User.email == email).one()

    def connection(self, name="Monzo", synced_ago=timedelta(hours=1), refresh_token="rt-SECRET-REFRESH"):
        token = user_crypto.current_dek.set(self.dek)
        try:
            conn = BankConnection(
                user_id=self.user.id, provider_id=f"ob-{name}-SECRET-PROVIDER", provider_name=name,
                access_token="at-SECRET-ACCESS", refresh_token=refresh_token,
                token_expires_at=NOW - timedelta(minutes=5),
                last_synced_at=None if synced_ago is None else NOW - synced_ago,
            )
            self.db.add(conn)
            self.db.flush()
            self.db.add(Account(
                user_id=self.user.id, bank_connection_id=conn.id, external_id=f"ext-{name}-SECRET-EXTERNAL",
                provider_name=name, account_type="TRANSACTION", display_name=f"{name} Current",
                current_balance=Decimal("100"), balance_updated_at=NOW - timedelta(hours=2),
            ))
            self.db.commit()
            return str(conn.id)
        finally:
            user_crypto.current_dek.reset(token)

    def status(self, token=None):
        res = self.client.get(f"{API}/banking/sync-status", headers=_bearer(token or self.web))
        assert res.status_code == 200, res.text
        return {c["connection_id"]: c for c in res.json()["connections"]}


@pytest.fixture
def no_truelayer(monkeypatch):
    """Any outbound HTTP call fails the test."""
    async def refuse(self, request, **kwargs):
        raise AssertionError(f"sync-status made an outbound call: {request.url}")
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)


def test_a_recent_sync_is_not_stale_but_consent_is_unknown(client, db_session, no_truelayer):
    w = World(client, db_session)
    cid = w.connection()
    conn = w.status()[cid]
    assert conn["stale"] is False
    assert conn["consent"] == "unknown"
    assert conn["provider"] == "Monzo"
    assert conn["accounts"] == [
        {"display_name": "Monzo Current", "balance_updated_at": conn["accounts"][0]["balance_updated_at"]}
    ]
    assert conn["accounts"][0]["balance_updated_at"] is not None


@pytest.mark.parametrize("hours,stale", [(47, False), (49, True), (24 * 30, True)])
def test_stale_after_48_hours(client, db_session, no_truelayer, hours, stale):
    w = World(client, db_session)
    cid = w.connection(synced_ago=timedelta(hours=hours))
    assert w.status()[cid]["stale"] is stale


def test_never_synced_is_stale(client, db_session, no_truelayer):
    w = World(client, db_session)
    cid = w.connection(synced_ago=None)
    conn = w.status()[cid]
    assert conn["stale"] is True and conn["last_synced_at"] is None


def test_a_lapsed_consent_is_expired_and_stale_even_if_synced_recently(client, db_session, no_truelayer):
    """Sync drops the refresh token when TrueLayer rejects it (consent lapsed
    or revoked): that connection can't sync again until reconnected."""
    w = World(client, db_session)
    cid = w.connection(synced_ago=timedelta(minutes=10), refresh_token=None)
    conn = w.status()[cid]
    assert conn["consent"] == "expired" and conn["stale"] is True


def test_output_is_exactly_the_allow_list_with_no_secrets(client, db_session, no_truelayer):
    w = World(client, db_session)
    w.connection()
    res = client.get(f"{API}/banking/sync-status", headers=_bearer(w.web))
    body = res.json()
    assert set(body) == {"connections"}
    for conn in body["connections"]:
        assert set(conn) == CONNECTION_KEYS
        for account in conn["accounts"]:
            assert set(account) == ACCOUNT_KEYS
    # Precondition: the fixture really holds these values, so their absence means something.
    assert "SECRET" not in res.text
    assert "token_expires_at" not in res.text and "expires" not in res.text


def test_only_the_callers_connections(client, db_session, no_truelayer):
    a = World(client, db_session, "a@example.com")
    a.connection()
    b = World(client, db_session, "b@example.com")
    assert b.status() == {}


def test_an_mcp_read_token_can_call_it(client, db_session, no_truelayer):
    w = World(client, db_session)
    cid = w.connection()
    assert cid in w.status(token=w.mcp)


def test_the_accounts_output_flags_a_stale_connection(client, db_session, no_truelayer):
    w = World(client, db_session)
    w.connection("Monzo", synced_ago=timedelta(hours=1))
    w.connection("Amex", synced_ago=timedelta(days=5))
    res = client.get(f"{API}/banking/accounts", headers=_bearer(w.mcp))
    assert res.status_code == 200
    by_name = {a["display_name"]: a for a in res.json()}
    assert by_name["Monzo Current"]["sync_stale"] is False
    assert by_name["Amex Current"]["sync_stale"] is True
    assert by_name["Amex Current"]["last_synced_at"] is not None
    assert "SECRET" not in res.text


def test_the_no_outbound_call_guard_fires(no_truelayer):
    """Self-test: the guard used above really catches an httpx call."""
    import asyncio

    async def call():
        async with httpx.AsyncClient() as c:
            await c.get("https://auth.truelayer.com/")

    with pytest.raises(AssertionError, match="outbound call"):
        asyncio.run(call())


def test_token_columns_are_never_selected_on_this_path(client, db_session, no_truelayer):
    """Whether a refresh token exists is asked in SQL (IS NULL); the token
    columns are never selected, so tokens aren't decrypted to build the status."""
    import re

    from sqlalchemy import event

    from tests.conftest import engine

    w = World(client, db_session)
    w.connection()
    statements: list[str] = []

    def capture(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        w.status()
        client.get(f"{API}/banking/accounts", headers=_bearer(w.web))
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert any("bank_connections" in s for s in selects)  # precondition: we saw the queries
    for sql in selects:
        assert "access_token" not in sql, sql
        assert not re.search(r"refresh_token(?!\s+IS\s+NULL)", sql), sql
