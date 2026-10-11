"""A bank sync is bounded (T-08-22 PR 2a, sec).

It runs inside the request (the DEK exists only there), so it must finish
well inside the 5-minute sync lease, and usually inside the MCP client's
wait (a bank with many accounts can run past that, which is safe): every
TrueLayer call has an explicit timeout of at most 10 s, and `POST
/banking/sync` starts a bank only while at least SYNC_START_MARGIN_SECONDS
of its 45 s budget remain. A started bank is never cancelled (that could
lose a token TrueLayer had just rotated, sec on #138). A bank not started
is reported `not_attempted`, never as synced, and the call is still a 200
with each connection's status, not a 500.
"""
import asyncio

import httpx

from app.routers import banking
from app.services import sync_lock
from app.services import truelayer as truelayer_module
from app.services.truelayer import truelayer_service
from tests.integration.test_bank_reauth import _load, _seed_expired_connection
from tests.integration.test_bank_sync_api import World


def test_every_truelayer_call_has_an_explicit_timeout_of_10s_or_less(client, db_session, monkeypatch):
    seen = []
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        seen.append(kwargs.get("timeout"))
        return real_client(*args, transport=httpx.MockTransport(lambda r: httpx.Response(503)), **kwargs)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient", factory)
    _seed_expired_connection(client, db_session)
    client.post("/api/v1/banking/sync/accounts")
    assert seen, "no TrueLayer client was made"
    for timeout in seen:
        assert isinstance(timeout, httpx.Timeout)
        assert all(t is not None and t <= 10 for t in (timeout.connect, timeout.read, timeout.write, timeout.pool))


def test_the_budget_is_well_inside_the_lease():
    assert banking.SYNC_BUDGET_SECONDS <= 45
    # A bank is only started with this much budget left, enough for a token
    # refresh and a data call at their timeouts.
    assert banking.SYNC_START_MARGIN_SECONDS >= 2 * truelayer_module.TRUELAYER_TIMEOUT_SECONDS
    # A started bank runs to the end (never cancelled): allow it a few calls past the budget.
    worst = banking.SYNC_BUDGET_SECONDS + 3 * truelayer_module.TRUELAYER_TIMEOUT_SECONDS
    assert worst < sync_lock.LEASE.total_seconds() / 2


def test_a_started_bank_is_never_cut_off_and_later_ones_are_not_attempted(client, db_session, monkeypatch):
    """sec and eng-a on #138: cancelling a bank mid-sync could lose a token
    TrueLayer had already rotated. A bank only starts with enough budget
    left, and then finishes."""
    w = World(client, db_session)
    w.connection("SLOWBANK")
    w.connection("NEXTBANK")
    reached = []

    async def slow_accounts(connection, db, skip_token_refresh=False):
        reached.append(connection.provider_name)
        await asyncio.sleep(0.5)
        return ["acct"]

    async def no_transactions(connection, db, days=90, skip_token_refresh=False):
        return 0

    monkeypatch.setattr(truelayer_service, "sync_accounts", slow_accounts)
    monkeypatch.setattr(truelayer_service, "sync_transactions", no_transactions)
    monkeypatch.setattr(banking, "SYNC_BUDGET_SECONDS", 0.4)
    monkeypatch.setattr(banking, "SYNC_START_MARGIN_SECONDS", 0.2)

    r = w.sync()
    assert r.status_code == 200, r.text
    by_bank = {c["provider"]: c["status"] for c in r.json()["connections"]}
    assert by_bank == {"SLOWBANK": "synced", "NEXTBANK": "not_attempted"}
    assert reached == ["SLOWBANK"]


def _rotating_truelayer(monkeypatch, refresh_delay=0.0, data_error=None):
    """TrueLayer that rotates the refresh token (after `refresh_delay`), then
    fails every data call with `data_error`."""
    real_client = httpx.AsyncClient

    async def handler(request):
        if request.url.path.endswith("/connect/token"):
            await asyncio.sleep(refresh_delay)
            return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600})
        raise data_error or httpx.ReadTimeout("slow bank", request=request)

    def factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient", factory)


def test_a_timeout_after_the_token_rotated_keeps_the_new_token(client, db_session, monkeypatch):
    """sec on #138: the refresh rotated the token, then a data call timed out."""
    conn_id, dek = _seed_expired_connection(client, db_session, refresh_token="old-refresh")
    _rotating_truelayer(monkeypatch)
    r = client.post("/api/v1/banking/sync")
    assert r.status_code == 200, r.text
    assert [c["status"] for c in r.json()["connections"]] == ["failed"]
    assert _load(db_session, conn_id, dek).refresh_token == "new-refresh"


def test_the_budget_running_out_during_a_refresh_keeps_the_new_token(client, db_session, monkeypatch):
    """sec on #138: the budget ends while TrueLayer is rotating the token.
    The bank isn't cancelled, so the rotated token is saved."""
    conn_id, dek = _seed_expired_connection(client, db_session, refresh_token="old-refresh")
    _rotating_truelayer(monkeypatch, refresh_delay=0.5)
    monkeypatch.setattr(banking, "SYNC_BUDGET_SECONDS", 0.3)
    monkeypatch.setattr(banking, "SYNC_START_MARGIN_SECONDS", 0.1)
    client.post("/api/v1/banking/sync")
    assert _load(db_session, conn_id, dek).refresh_token == "new-refresh"
