"""One bank sync per user at a time, across workers (T-08-22, sec), and
sync errors in fixed words.

Two concurrent refreshes of one connection used to race: TrueLayer rotates
the refresh token on use, so the loser's token is rejected and
`_ensure_fresh_token` dropped the *new* one, breaking the connection until
the user reconnected. The web sync routes now take a per-user lease held in
the database (`user_sync_locks`), so it holds across both uvicorn workers;
a second sync gets 429 with Retry-After and calls nothing. As a second
guard, a rejected refresh never drops a token that was rotated meanwhile.

`_sync_error` used to put the raw exception text in the response
(f"{provider}: {exc}"); it now uses fixed words (details stay in the logs).
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core import user_crypto
from app.models import BankConnection, User
from app.services import sync_lock
from app.services.truelayer import truelayer_service
from tests.conftest import TestingSessionLocal
from tests.integration.test_bank_reauth import EMAIL, _invalid_grant, _load, _seed_expired_connection, truelayer  # noqa: F401

SYNC_ROUTES = ("/api/v1/banking/sync/accounts", "/api/v1/banking/sync/transactions", "/api/v1/banking/sync")


def _user_id(db_session):
    return db_session.query(User).filter(User.email == EMAIL).one().id


def _post(client, route):
    return client.post(route, json={}) if route.endswith("transactions") else client.post(route)  # /sync takes no body


@pytest.mark.parametrize("route", SYNC_ROUTES)
def test_a_second_sync_while_one_runs_is_429_and_calls_nothing(client, db_session, truelayer, route):
    _seed_expired_connection(client, db_session)
    other = TestingSessionLocal()  # another worker's session
    try:
        with sync_lock.sync_lease(other, _user_id(db_session)):
            response = _post(client, route)
    finally:
        other.close()
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert "already running" in response.json()["detail"]
    assert truelayer["requests"] == []


def test_two_sessions_cannot_both_hold_the_lease(db_session):
    user = User(email="two@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    a, b = TestingSessionLocal(), TestingSessionLocal()
    try:
        with sync_lock.sync_lease(a, user.id):
            with pytest.raises(sync_lock.SyncBusy):
                with sync_lock.sync_lease(b, user.id):
                    pass
        with sync_lock.sync_lease(b, user.id):  # free again once released
            pass
    finally:
        a.close()
        b.close()


def test_the_lease_is_released_when_the_sync_fails(client, db_session, truelayer):
    _seed_expired_connection(client, db_session)
    truelayer["handler"] = _invalid_grant
    assert client.post("/api/v1/banking/sync/accounts").status_code == 409
    other = TestingSessionLocal()
    try:
        with sync_lock.sync_lease(other, _user_id(db_session)):
            pass
    finally:
        other.close()


def test_a_lease_left_by_a_crashed_worker_expires(db_session):
    user = User(email="crash@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    sync_lock.acquire(db_session, user.id)  # never released
    later = datetime.now(timezone.utc) + sync_lock.LEASE + timedelta(seconds=1)
    assert sync_lock.acquire(db_session, user.id, now=later) is not None


def test_a_rejected_refresh_keeps_a_token_rotated_meanwhile(client, db_session, truelayer):
    """Belt and braces: another sync rotated the token while ours was being
    rejected. The rejection is for the old token: the new one is kept."""
    conn_id, dek = _seed_expired_connection(client, db_session, refresh_token="old-refresh")

    def rotate_then_reject(request):
        other = TestingSessionLocal()
        ctx = user_crypto.current_dek.set(dek)
        try:
            other.get(BankConnection, conn_id).refresh_token = "rotated-refresh"
            other.commit()
        finally:
            user_crypto.current_dek.reset(ctx)
            other.close()
        return _invalid_grant(request)

    truelayer["handler"] = rotate_then_reject
    client.post("/api/v1/banking/sync/accounts")
    assert _load(db_session, conn_id, dek).refresh_token == "rotated-refresh"


def test_a_sync_error_is_fixed_words_never_the_exception(client, db_session, truelayer, monkeypatch):
    _seed_expired_connection(client, db_session)
    planted = "PLANTED secret-ish detail https://auth.truelayer.com/x?code=abc"

    async def boom(*_a, **_k):
        raise RuntimeError(planted)

    monkeypatch.setattr(truelayer_service, "sync_accounts", boom)
    response = client.post("/api/v1/banking/sync/accounts")
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "PLANTED" not in detail and "truelayer.com" not in detail
    assert "MONZO: couldn't sync right now" in detail
