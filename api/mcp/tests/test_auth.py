import httpx
import pytest

from auth import SCOPE_READ, SCOPE_RULES_WRITE, TokenInfoVerifier

API = "http://api.test/api/v1"
RESOURCE = "https://example.com/mcp"


def _verifier(handler) -> TokenInfoVerifier:
    return TokenInfoVerifier(API, RESOURCE, transport=httpx.MockTransport(handler))


def _active(**overrides):
    body = {
        "active": True,
        "client_id": "client-1",
        "scope": f"{SCOPE_READ} {SCOPE_RULES_WRITE}",
        "exp": 2_000_000_000,
        "aud": RESOURCE,
        "sub": "user-1",
    }
    body.update(overrides)
    return body


@pytest.mark.anyio
async def test_active_token_for_this_resource_is_accepted():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_active())

    token = await _verifier(handler).verify_token("tok")
    assert token is not None
    assert token.token == "tok"
    assert token.client_id == "client-1"
    assert token.scopes == [SCOPE_READ, SCOPE_RULES_WRITE]
    assert token.expires_at == 2_000_000_000
    assert token.subject == "user-1"
    assert seen == {"url": f"{API}/oauth/token-info", "auth": "Bearer tok"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404),  # API has no token-info endpoint (yet): fail closed
        httpx.Response(401),
        httpx.Response(500),
        httpx.Response(200, json=_active(active=False)),
        httpx.Response(200, json=_active(aud="https://elsewhere.example/mcp")),
        httpx.Response(200, json={k: v for k, v in _active().items() if k != "aud"}),
        httpx.Response(200, json={k: v for k, v in _active().items() if k != "client_id"}),
        httpx.Response(200, text="not json"),
    ],
    ids=["404", "401", "500", "inactive", "wrong-audience", "no-audience", "no-client", "garbage"],
)
async def test_anything_but_an_active_matching_token_is_rejected(response):
    assert await _verifier(lambda request: response).verify_token("tok") is None


@pytest.mark.anyio
async def test_audience_may_be_a_list():
    token = await _verifier(
        lambda r: httpx.Response(200, json=_active(aud=["other", RESOURCE]))
    ).verify_token("tok")
    assert token is not None


@pytest.mark.anyio
async def test_unreachable_api_is_rejected_not_raised():
    def handler(request):
        raise httpx.ConnectError("down")

    assert await _verifier(handler).verify_token("tok") is None
