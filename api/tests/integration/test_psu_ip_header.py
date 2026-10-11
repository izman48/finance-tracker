"""X-PSU-IP only on syncs the user starts in the web app (T-08-22, owner
"A + address", sec option B).

Sending the user's address tells the bank the user is present, so the read
doesn't count against the unattended-access limit. It goes only on a sync
the user starts in the web app: /banking/sync with a web session, the older
/sync/* routes and the first sync after connecting. Never on the MCP path:
there the user isn't at the bank interface, and the only address available
is the assistant's. It comes only from request.client.host (uvicorn sets
that from Caddy's X-Forwarded-For for the pinned proxy only); a header the
client sends is never read. It is never stored, logged or returned.
"""
import logging
import uuid
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import user_crypto
from app.main import app
from app.models import Account
from app.services import truelayer as truelayer_module
from tests.integration.test_bank_sync_api import World
from tests.integration.test_oauth import _bearer

PUBLIC = "81.2.69.142"


@pytest.fixture
def public_client(client):
    """The app as reached from a public address (the `client` fixture's DB override stays)."""
    with TestClient(app, client=(PUBLIC, 50000)) as c:
        yield c


@pytest.fixture
def bank(monkeypatch):
    """TrueLayer that records each data request's X-PSU-IP (or None)."""
    seen = []
    real_client = httpx.AsyncClient

    def handler(request):
        seen.append(request.headers.get("X-PSU-IP"))
        path = request.url.path
        if path.endswith("/data/v1/accounts"):
            return httpx.Response(200, json={"results": [{"account_id": "acc-1", "display_name": "Current"}]})
        if path.endswith("/balance"):
            return httpx.Response(200, json={"results": [{"current": 1, "available": 1}]})
        if path.endswith("/transactions"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404)

    monkeypatch.setattr(truelayer_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    return seen


def _world(public_client, db_session):
    w = World(public_client, db_session, email="psu@example.com")
    conn_id = w.connection("MONZO")
    ctx = user_crypto.current_dek.set(w.dek)
    try:
        db_session.add(Account(
            user_id=w.user.id, bank_connection_id=uuid.UUID(conn_id),
            external_id="acc-1", provider_name="MONZO", account_type="TRANSACTION", display_name="Current",
            current_balance=Decimal("1"),
        ))
        db_session.commit()
    finally:
        user_crypto.current_dek.reset(ctx)
    return w


def test_a_web_sync_sends_exactly_the_callers_address(public_client, db_session, bank):
    w = _world(public_client, db_session)
    r = public_client.post("/api/v1/banking/sync", headers=_bearer(w.web))
    assert r.status_code == 200, r.text
    assert bank and set(bank) == {PUBLIC}


def test_an_mcp_sync_never_sends_it(public_client, db_session, bank):
    w = _world(public_client, db_session)
    r = public_client.post("/api/v1/banking/sync", headers=_bearer(w.mcp))
    assert r.status_code == 200, r.text
    assert bank and set(bank) == {None}


@pytest.mark.parametrize("route,body", [
    ("/api/v1/banking/sync/accounts", None),
    ("/api/v1/banking/sync/transactions", {}),
])
def test_the_older_web_routes_send_it(public_client, db_session, bank, route, body):
    w = _world(public_client, db_session)
    r = public_client.post(route, headers=_bearer(w.web), json=body)
    assert r.status_code == 200, r.text
    assert bank and set(bank) == {PUBLIC}


def test_a_forged_forwarded_for_is_ignored(public_client, db_session, bank):
    w = _world(public_client, db_session)
    public_client.post("/api/v1/banking/sync", headers={**_bearer(w.web), "X-Forwarded-For": "1.2.3.4",
                                                        "X-Real-IP": "1.2.3.4"})
    assert "1.2.3.4" not in bank
    assert set(bank) == {PUBLIC}


def test_a_private_caller_sends_none(client, db_session, bank):
    """`client` connects as 'testclient': not an address, so no header."""
    w = _world(client, db_session)
    client.post("/api/v1/banking/sync", headers=_bearer(w.web))
    assert bank and set(bank) == {None}


def test_the_address_is_never_logged_or_returned(public_client, db_session, bank, caplog):
    w = _world(public_client, db_session)
    with caplog.at_level(logging.DEBUG):
        r = public_client.post("/api/v1/banking/sync", headers=_bearer(w.web))
    assert PUBLIC not in r.text
    assert PUBLIC not in "\n".join(rec.getMessage() for rec in caplog.records)


def test_the_address_does_not_leak_into_a_later_mcp_sync(public_client, db_session, bank):
    """Request-scoped: a web sync's address isn't left behind for the next call."""
    from app.services import sync_lock

    w = _world(public_client, db_session)
    public_client.post("/api/v1/banking/sync", headers=_bearer(w.web))
    bank.clear()
    db_session.query(sync_lock.UserSyncLock).update({"cooldown_from": None})
    db_session.commit()
    public_client.post("/api/v1/banking/sync", headers=_bearer(w.mcp))
    assert bank and set(bank) == {None}
