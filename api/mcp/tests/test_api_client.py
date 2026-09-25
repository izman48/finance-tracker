import httpx
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from api_client import (
    ApiClient,
    InsufficientScopeError,
    NotAuthenticatedError,
    PasswordCredentials,
    RequestBearerCredentials,
)
from auth import SCOPE_READ, SCOPE_RULES_WRITE

API = "http://api.test/api/v1"


def _as_user(token: str, scopes: list[str]):
    """Put an authenticated MCP request in context, as the SDK's middleware does."""
    user = AuthenticatedUser(AccessToken(token=token, client_id="c", scopes=scopes))
    return auth_context_var.set(user)


# --- Password credentials (stdio / local use) --------------------------------


@pytest.mark.anyio
async def test_password_logs_in_once_and_reuses_the_token():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "t1"})
        assert request.headers["authorization"] == "Bearer t1"
        return httpx.Response(200, json={"ok": True})

    client = ApiClient(API, PasswordCredentials(API, "a@b.c", "pw"), httpx.MockTransport(handler))
    assert await client.get("/analytics/summary") == {"ok": True}
    assert await client.get("/analytics/summary") == {"ok": True}
    assert calls.count("/api/v1/auth/login") == 1


@pytest.mark.anyio
async def test_password_re_logs_in_once_on_401():
    tokens = iter(["stale", "fresh"])

    def handler(request: httpx.Request):
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": next(tokens)})
        if request.headers["authorization"] == "Bearer stale":
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    client = ApiClient(API, PasswordCredentials(API, "a", "b"), httpx.MockTransport(handler))
    assert await client.get("/x") == {"ok": True}


@pytest.mark.anyio
async def test_password_mode_allows_every_scope():
    creds = PasswordCredentials(API, "a", "b")
    creds.require_scope(SCOPE_RULES_WRITE)  # the account owner holds every scope


# --- Request bearer credentials (remote / http) ------------------------------


@pytest.mark.anyio
async def test_bearer_forwards_the_callers_token():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={"id": 1})

    client = ApiClient(API, RequestBearerCredentials(), httpx.MockTransport(handler))
    reset = _as_user("user-token", [SCOPE_READ])
    try:
        assert await client.post("/rules/preview", {"pattern": "x"}) == {"id": 1}
    finally:
        auth_context_var.reset(reset)
    assert seen["auth"] == "Bearer user-token"
    assert b'"pattern"' in seen["body"]


@pytest.mark.anyio
async def test_bearer_without_an_authenticated_request_fails_closed():
    def handler(request):  # pragma: no cover - must never be reached
        raise AssertionError("no request may leave without a caller token")

    client = ApiClient(API, RequestBearerCredentials(), httpx.MockTransport(handler))
    with pytest.raises(NotAuthenticatedError):
        await client.get("/analytics/summary")


@pytest.mark.anyio
async def test_bearer_does_not_retry_on_401():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401)

    client = ApiClient(API, RequestBearerCredentials(), httpx.MockTransport(handler))
    reset = _as_user("t", [SCOPE_READ])
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/x")
    finally:
        auth_context_var.reset(reset)
    assert len(calls) == 1


def test_bearer_scope_check():
    creds = RequestBearerCredentials()
    reset = _as_user("t", [SCOPE_READ])
    try:
        creds.require_scope(SCOPE_READ)
        with pytest.raises(InsufficientScopeError, match=SCOPE_RULES_WRITE):
            creds.require_scope(SCOPE_RULES_WRITE)
    finally:
        auth_context_var.reset(reset)
