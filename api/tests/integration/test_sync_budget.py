"""A bank sync is bounded (T-08-22 PR 2a, sec).

It runs inside the request (the DEK exists only there), so it must finish
well inside the MCP client's wait and the 5-minute sync lease: every
TrueLayer call has an explicit timeout of at most 10 s, and the whole of
`POST /banking/sync` has a budget of at most 45 s. A bank not reached in
time is reported `not_attempted`, never as synced, and the call is still a
200 with each connection's status, not a 500.
"""
import asyncio

import httpx

from app.routers import banking
from app.services import sync_lock
from app.services import truelayer as truelayer_module
from app.services.truelayer import truelayer_service
from tests.integration.test_bank_reauth import _seed_expired_connection
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


def test_the_budget_is_well_inside_the_lease_and_the_mcp_wait():
    assert banking.SYNC_BUDGET_SECONDS <= 45
    # One call can overrun the budget by at most its own timeout.
    worst = banking.SYNC_BUDGET_SECONDS + truelayer_module.TRUELAYER_TIMEOUT_SECONDS
    assert worst < sync_lock.LEASE.total_seconds() / 4


def test_banks_not_reached_in_time_are_not_attempted_and_the_call_is_a_200(client, db_session, monkeypatch):
    w = World(client, db_session)
    w.connection("SLOWBANK")
    w.connection("NEXTBANK")
    reached = []

    async def slow_accounts(connection, db, skip_token_refresh=False):
        reached.append(connection.provider_name)
        await asyncio.sleep(1)
        return []

    async def no_transactions(connection, db, days=90, skip_token_refresh=False):
        return 0

    monkeypatch.setattr(truelayer_service, "sync_accounts", slow_accounts)
    monkeypatch.setattr(truelayer_service, "sync_transactions", no_transactions)
    monkeypatch.setattr(banking, "SYNC_BUDGET_SECONDS", 0.2)

    r = w.sync()
    assert r.status_code == 200, r.text
    statuses = sorted(c["status"] for c in r.json()["connections"])
    assert statuses == ["failed", "not_attempted"]  # cut off mid-sync, and never reached
    assert len(reached) == 1
