"""OAuth 2.1 authorization server for the remote MCP server.

Flow under test: a client registers itself (RFC 7591), sends the user to the
consent page, which POSTs the approval with the user's web session; the client
exchanges the code (PKCE S256) for a short-lived MCP access token plus a
rotating refresh token, and calls the scope-limited API routes with it.

The properties that matter: codes and refresh tokens are single-use, PKCE and
redirect URIs are enforced, an MCP token reaches only the MCP allowlist, and
password changes / refresh-token reuse cut every token off.
"""
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from jose import jwt

from app.core.config import get_settings
from app.models import OAuthAuthorizationCode, OAuthGrant

settings = get_settings()
ISSUER = settings.oauth_issuer
RESOURCE = settings.mcp_resource_url
READ, WRITE = "finance:read", "finance:rules.write"
REDIRECT = "https://client.example/callback"
PASSWORD = "securepassword123"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _web_login(client, email="oauth@example.com") -> str:
    client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    return client.post(
        "/api/v1/auth/login", data={"username": email, "password": PASSWORD}
    ).json()["access_token"]


def _register_client(client, redirect_uris=(REDIRECT,), **extra):
    return client.post(
        "/api/v1/oauth/register",
        json={"redirect_uris": list(redirect_uris), "client_name": "Test Client", **extra},
    )


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _authorize_params(client_id, challenge, redirect_uri=REDIRECT, **overrides):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz",
        "resource": RESOURCE,
    }
    params.update(overrides)
    return {k: v for k, v in params.items() if v is not None}


def _approve(client, web_token, params, scopes=(READ, WRITE), approve=True):
    return client.post(
        "/api/v1/oauth/authorize",
        json={**params, "approve": approve, "scopes": list(scopes)},
        headers={"Authorization": f"Bearer {web_token}"},
    )


def _code_from(redirect_to: str) -> str:
    return parse_qs(urlparse(redirect_to).query)["code"][0]


def _exchange(client, code, client_id, verifier, redirect_uri=REDIRECT, **extra):
    return client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            **extra,
        },
    )


def _refresh(client, refresh_token, client_id, **extra):
    return client.post(
        "/api/v1/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id, **extra},
    )


def _connect(client, scopes=(READ, WRITE), email="oauth@example.com"):
    """Run the whole flow; return (web_token, client_id, token response json)."""
    web = _web_login(client, email)
    client_id = _register_client(client).json()["client_id"]
    verifier, challenge = _pkce()
    r = _approve(client, web, _authorize_params(client_id, challenge), scopes)
    assert r.status_code == 200, r.text
    tokens = _exchange(client, _code_from(r.json()["redirect_to"]), client_id, verifier)
    assert tokens.status_code == 200, tokens.text
    return web, client_id, tokens.json()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Discovery & registration
# --------------------------------------------------------------------------- #
def test_authorization_server_metadata(client):
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    m = r.json()
    assert m["issuer"] == ISSUER
    assert m["authorization_endpoint"] == f"{ISSUER}/oauth/authorize"
    assert m["token_endpoint"] == f"{ISSUER}/api/v1/oauth/token"
    assert m["registration_endpoint"] == f"{ISSUER}/api/v1/oauth/register"
    assert m["code_challenge_methods_supported"] == ["S256"]
    assert m["response_types_supported"] == ["code"]
    assert set(m["grant_types_supported"]) == {"authorization_code", "refresh_token"}
    assert m["token_endpoint_auth_methods_supported"] == ["none"]
    assert set(m["scopes_supported"]) == {READ, WRITE}


def test_register_public_client(client):
    r = _register_client(client, redirect_uris=[REDIRECT, "http://localhost:33418/callback"])
    assert r.status_code == 201
    body = r.json()
    assert body["client_id"]
    assert body["redirect_uris"] == [REDIRECT, "http://localhost:33418/callback"]
    assert body["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in body


@pytest.mark.parametrize(
    "uris",
    [
        [],
        ["http://client.example/callback"],  # cleartext off-loopback
        ["https://client.example/cb#frag"],
        ["javascript:alert(1)"],
        ["not a url"],
    ],
)
def test_register_rejects_unsafe_redirect_uris(client, uris):
    r = _register_client(client, redirect_uris=uris)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_redirect_uri" or r.json()["error"] == "invalid_client_metadata"


def test_register_rejects_confidential_clients(client):
    r = _register_client(client, token_endpoint_auth_method="client_secret_basic")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client_metadata"


# --------------------------------------------------------------------------- #
# Authorize (consent)
# --------------------------------------------------------------------------- #
def test_authorize_details_for_the_consent_page(client):
    client_id = _register_client(client).json()["client_id"]
    _, challenge = _pkce()
    r = client.get("/api/v1/oauth/authorize/details", params=_authorize_params(client_id, challenge))
    assert r.status_code == 200
    assert r.json()["client_name"] == "Test Client"
    assert r.json()["redirect_host"] == "client.example"


@pytest.mark.parametrize("bad", ["client", "redirect"])
def test_unknown_client_or_redirect_is_never_redirected_to(client, bad):
    client_id = _register_client(client).json()["client_id"]
    _, challenge = _pkce()
    params = _authorize_params(client_id, challenge)
    if bad == "client":
        params["client_id"] = "nope"
    else:
        params["redirect_uri"] = "https://attacker.example/callback"
    r = client.get("/api/v1/oauth/authorize/details", params=params)
    assert r.status_code == 400
    assert "redirect_to" not in r.json()


@pytest.mark.parametrize(
    "override",
    [
        {"code_challenge_method": "plain"},
        {"code_challenge": None},
        {"response_type": "token"},
        {"resource": "https://elsewhere.example/mcp"},
        {"scope": "finance:everything"},
    ],
)
def test_bad_request_redirects_back_with_an_error(client, override):
    client_id = _register_client(client).json()["client_id"]
    _, challenge = _pkce()
    params = _authorize_params(client_id, challenge, **override)
    r = client.get("/api/v1/oauth/authorize/details", params=params)
    assert r.status_code == 400
    q = parse_qs(urlparse(r.json()["redirect_to"]).query)
    assert q["error"][0] and q["state"] == ["xyz"]
    assert r.json()["redirect_to"].startswith(REDIRECT)


def test_approval_requires_a_web_session(client):
    client_id = _register_client(client).json()["client_id"]
    _, challenge = _pkce()
    r = client.post(
        "/api/v1/oauth/authorize",
        json={**_authorize_params(client_id, challenge), "approve": True, "scopes": [READ]},
    )
    assert r.status_code == 401


def test_an_mcp_token_cannot_approve_new_grants(client):
    _, client_id, tokens = _connect(client)
    _, challenge = _pkce()
    r = _approve(client, tokens["access_token"], _authorize_params(client_id, challenge))
    assert r.status_code == 401


def test_denial_redirects_with_access_denied(client):
    web = _web_login(client)
    client_id = _register_client(client).json()["client_id"]
    _, challenge = _pkce()
    r = _approve(client, web, _authorize_params(client_id, challenge), approve=False)
    assert r.status_code == 200
    q = parse_qs(urlparse(r.json()["redirect_to"]).query)
    assert q == {"error": ["access_denied"], "state": ["xyz"]}


def test_approval_must_include_read(client):
    web = _web_login(client)
    client_id = _register_client(client).json()["client_id"]
    _, challenge = _pkce()
    r = _approve(client, web, _authorize_params(client_id, challenge), scopes=[WRITE])
    assert r.status_code == 400


def test_loopback_redirect_may_use_any_port(client):
    # RFC 8252 §7.3: native apps (Claude Code) pick a free port per sign-in.
    web = _web_login(client)
    client_id = _register_client(client, redirect_uris=["http://localhost:33418/callback"]).json()["client_id"]
    verifier, challenge = _pkce()
    used = "http://localhost:51234/callback"
    r = _approve(client, web, _authorize_params(client_id, challenge, redirect_uri=used))
    assert r.status_code == 200
    assert r.json()["redirect_to"].startswith(used)
    assert _exchange(client, _code_from(r.json()["redirect_to"]), client_id, verifier, redirect_uri=used).status_code == 200


def test_loopback_path_must_still_match(client):
    client_id = _register_client(client, redirect_uris=["http://localhost:33418/callback"]).json()["client_id"]
    _, challenge = _pkce()
    params = _authorize_params(client_id, challenge, redirect_uri="http://localhost:33418/other")
    assert client.get("/api/v1/oauth/authorize/details", params=params).status_code == 400


# --------------------------------------------------------------------------- #
# Code exchange
# --------------------------------------------------------------------------- #
def test_code_exchange_issues_access_and_refresh_tokens(client):
    _, _, tokens = _connect(client)
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 3600
    assert tokens["refresh_token"]
    assert set(tokens["scope"].split()) == {READ, WRITE}
    claims = jwt.get_unverified_claims(tokens["access_token"])
    assert claims["typ"] == "mcp_access" and claims["aud"] == RESOURCE


def test_token_responses_are_not_cached(client):
    web = _web_login(client)
    client_id = _register_client(client).json()["client_id"]
    verifier, challenge = _pkce()
    code = _code_from(_approve(client, web, _authorize_params(client_id, challenge)).json()["redirect_to"])
    r = _exchange(client, code, client_id, verifier)
    assert r.headers["cache-control"] == "no-store"


def test_code_is_single_use(client):
    web = _web_login(client)
    client_id = _register_client(client).json()["client_id"]
    verifier, challenge = _pkce()
    code = _code_from(_approve(client, web, _authorize_params(client_id, challenge)).json()["redirect_to"])
    assert _exchange(client, code, client_id, verifier).status_code == 200
    r = _exchange(client, code, client_id, verifier)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


@pytest.mark.parametrize("tamper", ["verifier", "redirect", "client", "expired", "resource"])
def test_code_exchange_rejects_mismatches(client, db_session, tamper):
    web = _web_login(client)
    client_id = _register_client(client).json()["client_id"]
    other_client = _register_client(client).json()["client_id"]
    verifier, challenge = _pkce()
    code = _code_from(_approve(client, web, _authorize_params(client_id, challenge)).json()["redirect_to"])
    kwargs = {}
    if tamper == "verifier":
        verifier = _pkce()[0]
    elif tamper == "redirect":
        kwargs["redirect_uri"] = "https://client.example/other"
    elif tamper == "client":
        client_id = other_client
    elif tamper == "expired":
        row = db_session.query(OAuthAuthorizationCode).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()
    elif tamper == "resource":
        kwargs["resource"] = "https://elsewhere.example/mcp"
    r = _exchange(client, code, client_id, verifier, **kwargs)
    assert r.status_code == 400
    assert r.json()["error"] in ("invalid_grant", "invalid_target")


def test_a_failed_exchange_still_burns_the_code(client):
    # A guessed verifier must not leave the code usable for another try.
    web = _web_login(client)
    client_id = _register_client(client).json()["client_id"]
    verifier, challenge = _pkce()
    code = _code_from(_approve(client, web, _authorize_params(client_id, challenge)).json()["redirect_to"])
    assert _exchange(client, code, client_id, _pkce()[0]).status_code == 400
    assert _exchange(client, code, client_id, verifier).status_code == 400


def test_unsupported_grant_type(client):
    r = client.post("/api/v1/oauth/token", data={"grant_type": "password", "username": "a", "password": "b"})
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"


def test_codes_and_refresh_tokens_are_stored_only_as_hashes(client, db_session):
    _, _, tokens = _connect(client)
    grant = db_session.query(OAuthGrant).one()
    assert tokens["refresh_token"] not in (grant.refresh_token_hash, grant.wrapped_dek)
    assert db_session.query(OAuthAuthorizationCode).count() == 0  # consumed


# --------------------------------------------------------------------------- #
# Using the access token
# --------------------------------------------------------------------------- #
def test_mcp_token_reads_encrypted_data(client):
    web, _, tokens = _connect(client)
    client.post(
        "/api/v1/rules/packs/bulk",
        json={"name": "Mine", "rules": [{"pattern": "TESCO", "category": "Groceries"}], "apply": False},
        headers=_bearer(web),
    )
    r = client.get("/api/v1/rules", headers=_bearer(tokens["access_token"]))
    assert r.status_code == 200
    assert r.json()["packs"][0]["rules"][0]["pattern"] == "TESCO"  # decrypted with the DEK


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/analytics/summary"),
        ("get", "/api/v1/analytics/forecast"),
        ("get", "/api/v1/analytics/spending"),
        ("get", "/api/v1/analytics/spending/trend"),
        ("get", "/api/v1/analytics/commitments"),
        ("get", "/api/v1/banking/accounts"),
        ("get", "/api/v1/banking/transactions"),
        ("get", "/api/v1/rules"),
        ("get", "/api/v1/rules/impact"),
    ],
)
def test_mcp_token_reaches_the_read_allowlist(client, method, path):
    _, _, tokens = _connect(client, scopes=[READ])
    r = getattr(client, method)(path, headers=_bearer(tokens["access_token"]))
    assert r.status_code == 200, r.text


def test_preview_is_a_read(client):
    _, _, tokens = _connect(client, scopes=[READ])
    r = client.post("/api/v1/rules/preview", json={"pattern": "x"}, headers=_bearer(tokens["access_token"]))
    assert r.status_code == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/auth/me"),
        ("post", "/api/v1/auth/change-password"),
        ("post", "/api/v1/auth/delete-account"),
        ("get", "/api/v1/banking/connect"),
        ("post", "/api/v1/banking/disconnect"),
        ("post", "/api/v1/rules/apply"),
        ("post", "/api/v1/rules/packs"),
        ("get", "/api/v1/assets"),
        ("get", "/api/v1/analytics/net-worth-position"),
    ],
)
def test_mcp_token_is_refused_everywhere_else(client, method, path):
    _, _, tokens = _connect(client)
    r = getattr(client, method)(path, headers=_bearer(tokens["access_token"]), **({"json": {}} if method == "post" else {}))
    assert r.status_code == 401


def test_rule_pack_needs_the_write_scope(client):
    _, _, tokens = _connect(client, scopes=[READ])
    r = client.post(
        "/api/v1/rules/packs/bulk",
        json={"name": "P", "rules": [{"pattern": "X", "category": "Y"}]},
        headers=_bearer(tokens["access_token"]),
    )
    assert r.status_code == 403


def test_rule_pack_with_the_write_scope(client):
    _, _, tokens = _connect(client, scopes=[READ, WRITE])
    r = client.post(
        "/api/v1/rules/packs/bulk",
        json={"name": "P", "rules": [{"pattern": "X", "category": "Y"}]},
        headers=_bearer(tokens["access_token"]),
    )
    assert r.status_code == 201


def test_token_for_another_audience_is_refused(client):
    _, _, tokens = _connect(client)
    claims = jwt.get_unverified_claims(tokens["access_token"])
    forged = jwt.encode({**claims, "aud": "https://elsewhere.example/mcp"}, settings.secret_key, algorithm="HS256")
    assert client.get("/api/v1/rules", headers=_bearer(forged)).status_code == 401
    assert client.get("/api/v1/oauth/token-info", headers=_bearer(forged)).status_code == 401


# --------------------------------------------------------------------------- #
# token-info (what the MCP server asks)
# --------------------------------------------------------------------------- #
def test_token_info_describes_an_mcp_token(client):
    _, client_id, tokens = _connect(client, scopes=[READ])
    r = client.get("/api/v1/oauth/token-info", headers=_bearer(tokens["access_token"]))
    assert r.status_code == 200
    info = r.json()
    assert info["active"] is True
    assert info["client_id"] == client_id
    assert info["scope"] == READ
    assert info["aud"] == RESOURCE
    assert info["sub"] and info["exp"]


def test_token_info_refuses_web_sessions_and_garbage(client):
    web = _web_login(client)
    assert client.get("/api/v1/oauth/token-info", headers=_bearer(web)).status_code == 401
    assert client.get("/api/v1/oauth/token-info", headers=_bearer("garbage")).status_code == 401
    assert client.get("/api/v1/oauth/token-info").status_code == 401


# --------------------------------------------------------------------------- #
# Refresh: rotation, reuse detection, idle expiry, revocation
# --------------------------------------------------------------------------- #
def test_refresh_rotates_and_keeps_data_readable(client):
    _, client_id, first = _connect(client)
    r = _refresh(client, first["refresh_token"], client_id)
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert client.get("/api/v1/rules", headers=_bearer(second["access_token"])).status_code == 200
    # And again from the rotated token — the DEK was re-wrapped under it.
    assert _refresh(client, second["refresh_token"], client_id).status_code == 200


def test_refresh_can_narrow_but_not_widen_scope(client):
    _, client_id, first = _connect(client, scopes=[READ])
    r = _refresh(client, first["refresh_token"], client_id, scope=f"{READ} {WRITE}")
    assert r.status_code == 400 and r.json()["error"] == "invalid_scope"

    _, client_id, first = _connect(client, email="other@example.com")
    r = _refresh(client, first["refresh_token"], client_id, scope=READ)
    assert r.status_code == 200 and r.json()["scope"] == READ


def test_reusing_a_rotated_refresh_token_revokes_the_grant(client):
    _, client_id, first = _connect(client)
    second = _refresh(client, first["refresh_token"], client_id).json()

    replay = _refresh(client, first["refresh_token"], client_id)
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    # Theft is assumed: the legitimate holder is cut off too, tokens included.
    assert _refresh(client, second["refresh_token"], client_id).status_code == 400
    assert client.get("/api/v1/oauth/token-info", headers=_bearer(second["access_token"])).status_code == 401
    assert client.get("/api/v1/rules", headers=_bearer(second["access_token"])).status_code == 401


def test_refresh_token_is_bound_to_its_client(client):
    _, _, first = _connect(client)
    other = _register_client(client).json()["client_id"]
    assert _refresh(client, first["refresh_token"], other).status_code == 400


def test_idle_grant_expires_after_30_days(client, db_session):
    _, client_id, first = _connect(client)
    grant = db_session.query(OAuthGrant).one()
    assert (grant.expires_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days in (29, 30)
    grant.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    r = _refresh(client, first["refresh_token"], client_id)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_password_change_cuts_off_mcp_tokens(client):
    web, client_id, tokens = _connect(client)
    r = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "anotherpassword456"},
        headers=_bearer(web),
    )
    assert r.status_code == 200
    assert client.get("/api/v1/rules", headers=_bearer(tokens["access_token"])).status_code == 401
    assert client.get("/api/v1/oauth/token-info", headers=_bearer(tokens["access_token"])).status_code == 401
    assert _refresh(client, tokens["refresh_token"], client_id).status_code == 400


def test_garbage_refresh_token(client):
    client_id = _register_client(client).json()["client_id"]
    r = _refresh(client, "nope", client_id)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
