"""Write auth for Claude's planning tools (T-08-3a).

The control is at the API, not in the MCP server: the client holds the token
and the API is public, so a token can call a write route directly. These
tests call a probe route that uses the real `PlanningWriter` dependency, the
same way the planning write routes (T-08-3b onwards) will.

  - scope: only a token granted `finance:planning.write` gets through;
  - claims: the dependency hands the route the grant and client id from the
    verified token, never from anything the caller sends;
  - revocation: a revoked grant or a password change stops the next write;
  - rate limit: 30 writes/hour per *user* (not per IP: every MCP call comes
    from the MCP container), plus a separate, looser dry-run budget.
"""
from datetime import datetime, timezone

import pytest
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.oauth_tokens import Caller
from app.core.planning_write import DRY_RUN_LIMIT, WRITE_LIMIT, PlanningWriter
from app.main import app
from app.models import OAuthGrant, User
from tests.integration.test_oauth import (
    PASSWORD,
    READ,
    WRITE as RULES_WRITE,
    _bearer,
    _connect,
    _refresh,
    _web_login,
)

PLANNING = "finance:planning.write"
PROBE = "/api/v1/__test__/planning-write"


class ProbeBody(BaseModel):
    dry_run: bool = True


calls: list[Caller] = []


@pytest.fixture(autouse=True)
def probe_route():
    """Mount a write route guarded by PlanningWriter for the length of a test."""
    router = APIRouter()

    @router.post(PROBE)
    def probe(body: ProbeBody, caller: PlanningWriter) -> dict:
        calls.append(caller)
        return {
            "user_id": str(caller.user.id),
            "grant_id": str(caller.grant_id) if caller.grant_id else None,
            "client_id": caller.client_id,
            "dry_run": body.dry_run,
        }

    before = list(app.router.routes)
    app.include_router(router)
    calls.clear()
    yield
    app.router.routes[:] = before


def _write(client, token, dry_run=False, **extra):
    return client.post(PROBE, json={"dry_run": dry_run}, headers={**_bearer(token), **extra})


def test_metadata_advertises_the_planning_scope(client):
    scopes = client.get("/.well-known/oauth-authorization-server").json()["scopes_supported"]
    assert PLANNING in scopes


@pytest.mark.parametrize("scopes", [(READ,), (READ, RULES_WRITE)])
def test_a_token_without_the_planning_scope_is_refused_at_the_api(client, scopes):
    _, _, tokens = _connect(client, scopes=scopes)
    r = _write(client, tokens["access_token"])
    assert r.status_code == 403
    assert 'error="insufficient_scope"' in r.headers["www-authenticate"]
    assert PLANNING in r.headers["www-authenticate"]
    assert calls == []


def test_the_planning_scope_reaches_the_route_with_verified_claims(client, db_session):
    _, client_id, tokens = _connect(client, scopes=(READ, PLANNING))
    grant = db_session.query(OAuthGrant).one()

    r = _write(client, tokens["access_token"], **{"X-Client-Id": "evil", "X-Grant-Id": "evil"})

    assert r.status_code == 200, r.text
    assert r.json()["grant_id"] == str(grant.id)
    assert r.json()["client_id"] == client_id == grant.client_id
    assert r.json()["user_id"] == str(grant.user_id)


def test_a_web_session_writes_with_no_grant(client):
    web = _web_login(client)
    r = _write(client, web)
    assert r.status_code == 200, r.text
    assert r.json()["grant_id"] is None and r.json()["client_id"] is None


def test_a_revoked_grant_stops_the_next_write(client, db_session):
    _, _, tokens = _connect(client, scopes=(READ, PLANNING))
    assert _write(client, tokens["access_token"]).status_code == 200

    grant = db_session.query(OAuthGrant).one()
    grant.revoked_at = datetime.now(timezone.utc)
    db_session.commit()

    assert _write(client, tokens["access_token"]).status_code == 401
    assert len(calls) == 1


def test_a_password_change_stops_the_next_write(client):
    web, _, tokens = _connect(client, scopes=(READ, PLANNING))
    r = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "anotherpassword456"},
        headers=_bearer(web),
    )
    assert r.status_code == 200
    assert _write(client, tokens["access_token"]).status_code == 401
    assert calls == []


def test_an_existing_grant_cannot_gain_the_planning_scope_on_refresh(client):
    _, client_id, tokens = _connect(client, scopes=(READ, RULES_WRITE))
    r = _refresh(client, tokens["refresh_token"], client_id, scope=f"{READ} {PLANNING}")
    assert r.status_code == 400 and r.json()["error"] == "invalid_scope"


def test_approving_without_the_box_grants_no_planning_scope(client):
    _, _, tokens = _connect(client, scopes=(READ, RULES_WRITE))
    assert PLANNING not in tokens["scope"].split()


# --- rate limit -----------------------------------------------------------------


def test_writes_are_limited_per_user_not_per_ip(client, db_session):
    _, _, a = _connect(client, scopes=(READ, PLANNING), email="a@example.com")
    _, _, b = _connect(client, scopes=(READ, PLANNING), email="b@example.com")

    for _ in range(WRITE_LIMIT):
        assert _write(client, a["access_token"]).status_code == 200
    over = _write(client, a["access_token"])
    assert over.status_code == 429
    assert int(over.headers["retry-after"]) > 0

    # Same client IP (TestClient), different user: B has its own budget.
    assert _write(client, b["access_token"]).status_code == 200


def test_dry_runs_have_their_own_looser_budget(client):
    _, _, a = _connect(client, scopes=(READ, PLANNING))
    for _ in range(WRITE_LIMIT):
        assert _write(client, a["access_token"]).status_code == 200
    assert _write(client, a["access_token"]).status_code == 429

    # Writes exhausted, previews still work, up to their own limit.
    assert DRY_RUN_LIMIT > WRITE_LIMIT
    for _ in range(DRY_RUN_LIMIT):
        assert _write(client, a["access_token"], dry_run=True).status_code == 200
    assert _write(client, a["access_token"], dry_run=True).status_code == 429


@pytest.mark.parametrize("dry_run", ["false", 0, "true", None])
def test_anything_but_a_literal_true_counts_as_a_write(client, dry_run):
    """Pydantic coerces "false"/0 to False, so only JSON `true` (or no field,
    which the routes default to true) may use the looser dry-run budget."""
    _, _, a = _connect(client, scopes=(READ, PLANNING))
    for _ in range(WRITE_LIMIT):
        assert _write(client, a["access_token"]).status_code == 200
    r = client.post(PROBE, json={"dry_run": dry_run}, headers=_bearer(a["access_token"]))
    assert r.status_code == 429


def test_a_missing_dry_run_is_a_preview(client):
    _, _, a = _connect(client, scopes=(READ, PLANNING))
    for _ in range(WRITE_LIMIT):
        assert _write(client, a["access_token"]).status_code == 200
    r = client.post(PROBE, json={}, headers=_bearer(a["access_token"]))
    assert r.status_code == 200 and r.json()["dry_run"] is True


def test_refused_calls_do_not_spend_the_budget(client):
    _, _, read_only = _connect(client, scopes=(READ,))
    for _ in range(WRITE_LIMIT + 5):
        assert _write(client, read_only["access_token"]).status_code == 403
    # The same user connects again, this time granting the scope.
    _, _, tokens = _connect(client, scopes=(READ, PLANNING))
    for _ in range(WRITE_LIMIT):
        assert _write(client, tokens["access_token"]).status_code == 200


# --- client_name ------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "Claude\u202eDesktop",        # right-to-left override
    "Claude\u2066Desktop\u2069",  # isolates
    "Claude\u200bDesktop",        # zero-width space
    "Claude\ufeffDesktop",        # BOM / zero-width no-break space
    "Claude\u200dDesktop",        # zero-width joiner
    "Claude\x07Desktop",          # control character
    "Claude\nDesktop",            # line break
    "Claude\u3164Desktop",        # Hangul filler (renders blank)
])
def test_register_refuses_invisible_or_bidi_characters_in_client_name(client, name):
    r = client.post(
        "/api/v1/oauth/register",
        json={"redirect_uris": ["https://client.example/callback"], "client_name": name},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client_metadata"


@pytest.mark.parametrize("name", ["Claude Desktop", "Clàude Désktop", "クロード", "My app (beta) 2"])
def test_register_accepts_ordinary_client_names(client, name):
    r = client.post(
        "/api/v1/oauth/register",
        json={"redirect_uris": ["https://client.example/callback"], "client_name": name},
    )
    assert r.status_code == 201, r.text
    assert r.json()["client_name"] == name


def test_user_lookup_is_by_token_not_db_order(client, db_session):
    """Guard: the probe's user is the token's user even with others present."""
    _web_login(client, "first@example.com")
    _, _, tokens = _connect(client, scopes=(READ, PLANNING), email="second@example.com")
    second = db_session.query(User).filter(User.email == "second@example.com").one()
    assert _write(client, tokens["access_token"]).json()["user_id"] == str(second.id)


def test_a_malformed_body_still_spends_the_write_budget(client):
    """The limit runs before the body is validated, so a 422 counts. That is
    deliberate (the stricter side): a caller can't probe for free with bad
    requests. Only refused auth (401/403) is free, as above."""
    _, _, a = _connect(client, scopes=(READ, PLANNING))
    for _ in range(WRITE_LIMIT):
        r = client.post(PROBE, json={"dry_run": [1]}, headers=_bearer(a["access_token"]))
        assert r.status_code == 422
    assert _write(client, a["access_token"]).status_code == 429
