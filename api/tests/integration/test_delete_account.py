"""Delete-account removes everything, with foreign keys on, and revokes the
bank tokens (T-12-10a; sec T-12-10a).

The table list comes from `Base.metadata`: every table with a foreign key to
`users` must hold no row of the deleted user afterwards, and another user's
rows are untouched. SQLite enforces foreign keys here (asserted), as Postgres
does, so a delete that only worked with them off fails (#180). TrueLayer
ends every connection by its documented call, `DELETE {auth}/api/delete`
with the access token as bearer (sec on #244: TrueLayer has no
`/connect/token/revoke`); an expired access token (401) is refreshed once
with the refresh token and the delete retried. Each call has the client
timeout and the whole loop an overall cap; a failure never blocks the
deletion, and no token value is ever logged. Synthetic data only.
"""
import asyncio
import logging
import time

import httpx
import pytest
from sqlalchemy import func, select, text

from app.core import user_crypto
from app.core.database import Base
from app.models import BankConnection
from app.services import truelayer
from tests.integration.test_reset_purge import BYSTANDER, PASSWORD, VICTIM, _bearer, _dek, _seed_everything, _signup, _user

API = "/api/v1"
SECRET_ACCESS, SECRET_REFRESH = "fake-access-two", "fake-refresh-two"


def user_tables():
    """Every table with a foreign key to users.id, and that column."""
    out = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if any(fk.column.table.name == "users" for fk in column.foreign_keys):
                out.append((table, column))
    return out


def _owned(db, user_id) -> dict[str, int]:
    return {
        t.name: db.execute(select(func.count()).select_from(t).where(c == user_id)).scalar()
        for t, c in user_tables()
    }


class Revokes:
    """A mocked TrueLayer auth server: records the bearer of each connection
    delete, answers 401 for `expired` access tokens, and refreshes them."""

    def __init__(self, fail=False, expired=(), delay=0.0):
        self.deleted, self.refreshed, self.timeouts = [], [], []
        self.fail, self.expired, self.delay = fail, set(expired), delay

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise httpx.ConnectError("unreachable")
        self.timeouts.append(request.extensions.get("timeout"))
        if request.method == "POST" and request.url.path.endswith("/connect/token"):
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            self.refreshed.append(form["refresh_token"])
            return httpx.Response(200, json={"access_token": f"renewed-for-{form['refresh_token']}"})
        assert (request.method, request.url.path) == ("DELETE", "/api/delete")
        bearer = request.headers["Authorization"].removeprefix("Bearer ")
        if bearer in self.expired:
            return httpx.Response(401)
        self.deleted.append(bearer)
        return httpx.Response(200)


@pytest.fixture
def world(client, db_session, monkeypatch):
    tokens = {}
    for email in (VICTIM, BYSTANDER):
        tokens[email] = _signup(client, email)
        _seed_everything(db_session, _user(db_session, email).id, _dek(tokens[email]))
    # A second connection with distinctive tokens, to look for in the logs.
    victim = _user(db_session, VICTIM)
    ctx = user_crypto.current_dek.set(_dek(tokens[VICTIM]))
    try:
        db_session.add(BankConnection(user_id=victim.id, provider_id="ob-two", provider_name="Two",
                                      access_token=SECRET_ACCESS, refresh_token=SECRET_REFRESH))
        db_session.commit()
    finally:
        user_crypto.current_dek.reset(ctx)
    return tokens


@pytest.fixture
def fk_on(db_session):
    """Foreign keys enforced, as on Postgres; the deletion relies on them."""
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    assert db_session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    yield
    db_session.rollback()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")


def _mock_truelayer(monkeypatch, revokes: Revokes):
    real = httpx.AsyncClient
    monkeypatch.setattr(truelayer.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(revokes.handler), **kw))


def _delete(client, token):
    return client.post(f"{API}/auth/delete-account", json={"password": PASSWORD}, headers=_bearer(token))


def test_every_user_table_is_found_from_metadata():
    names = {t.name for t, _ in user_tables()}
    assert {"bank_connections", "commitment_rules", "planned_items", "liabilities", "card_plans", "budgets",
            "audit_entries", "commitment_links"} <= names


def test_delete_account_leaves_no_row_of_the_user_with_foreign_keys_on(client, db_session, world, monkeypatch, fk_on):
    _mock_truelayer(monkeypatch, Revokes())
    victim, bystander = _user(db_session, VICTIM).id, _user(db_session, BYSTANDER).id
    before_victim, before_bystander = _owned(db_session, victim), _owned(db_session, bystander)
    assert sum(1 for n in before_victim.values() if n) >= 15  # the seed reached most tables
    res = _delete(client, world[VICTIM])
    assert res.status_code == 200, res.text
    db_session.expire_all()
    assert {t: n for t, n in _owned(db_session, victim).items() if n} == {}
    assert _owned(db_session, bystander) == before_bystander
    assert db_session.connection().exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    assert db_session.execute(text("SELECT count(*) FROM users WHERE id = :u"), {"u": victim.hex}).scalar() == 0


def test_every_connection_is_deleted_at_truelayer_with_a_timeout(client, db_session, world, monkeypatch, caplog, fk_on):
    revokes = Revokes()
    _mock_truelayer(monkeypatch, revokes)
    caplog.set_level(logging.DEBUG)
    assert _delete(client, world[VICTIM]).status_code == 200
    assert sorted(revokes.deleted) == sorted(["access", SECRET_ACCESS])
    assert revokes.refreshed == []
    assert all(t and t.get("connect") for t in revokes.timeouts)
    assert SECRET_ACCESS not in caplog.text and SECRET_REFRESH not in caplog.text


def test_an_expired_access_token_is_refreshed_once_then_the_connection_deleted(client, world, monkeypatch, caplog, fk_on):
    revokes = Revokes(expired={SECRET_ACCESS})
    _mock_truelayer(monkeypatch, revokes)
    caplog.set_level(logging.DEBUG)
    assert _delete(client, world[VICTIM]).status_code == 200
    assert revokes.refreshed == [SECRET_REFRESH]
    assert sorted(revokes.deleted) == sorted(["access", f"renewed-for-{SECRET_REFRESH}"])
    assert SECRET_REFRESH not in caplog.text and "renewed-for" not in caplog.text


def test_a_slow_truelayer_never_holds_the_deletion_past_the_overall_cap(client, db_session, world, monkeypatch, caplog, fk_on):
    from app.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "REVOKE_TOTAL_SECONDS", 0.2)
    _mock_truelayer(monkeypatch, Revokes(delay=5))
    caplog.set_level(logging.DEBUG)
    victim = _user(db_session, VICTIM).id
    started = time.perf_counter()
    assert _delete(client, world[VICTIM]).status_code == 200
    assert time.perf_counter() - started < 2
    db_session.expire_all()
    assert {t: n for t, n in _owned(db_session, victim).items() if n} == {}
    assert "timed out" in caplog.text.lower()


def test_a_failed_revoke_never_blocks_the_deletion_and_logs_no_token(client, db_session, world, monkeypatch, caplog, fk_on):
    _mock_truelayer(monkeypatch, Revokes(fail=True))
    caplog.set_level(logging.DEBUG)
    victim = _user(db_session, VICTIM).id
    assert _delete(client, world[VICTIM]).status_code == 200
    db_session.expire_all()
    assert {t: n for t, n in _owned(db_session, victim).items() if n} == {}
    assert "deletion at truelayer failed" in caplog.text.lower()
    assert SECRET_ACCESS not in caplog.text and SECRET_REFRESH not in caplog.text


def test_a_wrong_password_deletes_and_revokes_nothing(client, db_session, world, monkeypatch):
    revokes = Revokes()
    _mock_truelayer(monkeypatch, revokes)
    res = client.post(f"{API}/auth/delete-account", json={"password": "wrong-password-1"}, headers=_bearer(world[VICTIM]))
    assert res.status_code == 403
    assert revokes.deleted == []
    assert _owned(db_session, _user(db_session, VICTIM).id)["bank_connections"] == 2


def test_disconnecting_a_bank_deletes_its_connection_at_truelayer_too(client, db_session, world, monkeypatch, fk_on):
    revokes = Revokes()
    _mock_truelayer(monkeypatch, revokes)
    ctx = user_crypto.current_dek.set(_dek(world[VICTIM]))
    try:
        victim = _user(db_session, VICTIM).id
        two = next(c.id for c in db_session.query(BankConnection).filter(BankConnection.user_id == victim)
                   if c.access_token == SECRET_ACCESS)
    finally:
        user_crypto.current_dek.reset(ctx)
    assert client.delete(f"{API}/banking/connections/{two}", headers=_bearer(world[VICTIM])).status_code == 200
    assert revokes.deleted == [SECRET_ACCESS]
    assert client.post(f"{API}/banking/disconnect", headers=_bearer(world[VICTIM])).status_code == 200
    assert sorted(revokes.deleted) == sorted([SECRET_ACCESS, "access"])


# --- T-16-5: an unreadable token, and the order of revoke and delete ---------------------

ALIEN_ACCESS, ALIEN_REFRESH = "fake-access-alien", "fake-refresh-alien"


def _add_unreadable_connection(db_session, world):
    """A victim's connection whose tokens are under another key, so the
    victim's session can't decrypt them (as with a lost or rotated key)."""
    victim = _user(db_session, VICTIM)
    ctx = user_crypto.current_dek.set(_dek(world[BYSTANDER]))
    try:
        db_session.add(BankConnection(user_id=victim.id, provider_id="ob-alien", provider_name="Alien",
                                      access_token=ALIEN_ACCESS, refresh_token=ALIEN_REFRESH))
        db_session.commit()
    finally:
        user_crypto.current_dek.reset(ctx)
    db_session.expunge_all()  # no decrypted copy left in the identity map


def test_a_token_that_cannot_be_decrypted_is_skipped_and_the_account_still_deleted(
        client, db_session, world, monkeypatch, caplog, fk_on):
    _add_unreadable_connection(db_session, world)
    revokes = Revokes()
    _mock_truelayer(monkeypatch, revokes)
    caplog.set_level(logging.DEBUG)
    victim = _user(db_session, VICTIM).id
    assert _owned(db_session, victim)["bank_connections"] == 3

    res = _delete(client, world[VICTIM])
    assert res.status_code == 200, res.text
    assert res.json() == {"message": "Account and all associated data deleted."}
    assert sorted(revokes.deleted) == sorted(["access", SECRET_ACCESS])  # the unreadable one is skipped
    assert "could not read a bank connection's tokens" in caplog.text.lower()
    for secret in (ALIEN_ACCESS, ALIEN_REFRESH, SECRET_ACCESS, SECRET_REFRESH):
        assert secret not in caplog.text
    db_session.expire_all()
    assert {t: n for t, n in _owned(db_session, victim).items() if n} == {}


def test_every_revoke_happens_before_the_connections_are_deleted(client, db_session, world, monkeypatch, fk_on):
    victim = _user(db_session, VICTIM).id
    rows_at_each_revoke = []

    class Watching(Revokes):
        async def handler(self, request: httpx.Request) -> httpx.Response:
            rows_at_each_revoke.append(db_session.execute(
                text("SELECT count(*) FROM bank_connections WHERE user_id = :u"), {"u": victim.hex}).scalar())
            return await super().handler(request)
    revokes = Watching()
    _mock_truelayer(monkeypatch, revokes)

    assert _delete(client, world[VICTIM]).status_code == 200
    assert len(revokes.deleted) == 2
    assert rows_at_each_revoke == [2, 2]
    db_session.expire_all()
    assert _owned(db_session, victim)["bank_connections"] == 0
