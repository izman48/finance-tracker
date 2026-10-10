"""sync_status: a read-only view of how fresh each bank connection is (T-08-11).

The API (tested in api/tests) decides staleness and what is returned; the
tool only forwards it and explains the fields.
"""
import httpx
import pytest

from config import Settings
from server import create_server


class FakeApi:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "pw-token"})
        return httpx.Response(200, json={"connections": []})


def _server(api):
    settings = Settings("stdio", "http://api.test/api/v1", email="e@example.com", password="pw")
    return create_server(settings, api_transport=httpx.MockTransport(api))


@pytest.mark.anyio
async def test_reads_the_sync_status_route():
    api = FakeApi()
    await _server(api).call_tool("sync_status", {})
    calls = [r for r in api.requests if not r.url.path.endswith("/auth/login")]
    assert [(r.method, r.url.path) for r in calls] == [("GET", "/api/v1/banking/sync-status")]


@pytest.mark.anyio
async def test_is_read_only_and_explains_stale_and_unknown_consent():
    tools = {t.name: t for t in await _server(FakeApi()).list_tools()}
    tool = tools["sync_status"]
    assert tool.annotations.readOnlyHint is True
    text = tool.description
    assert "48" in text and "stale" in text and "unknown" in text
    assert "never" in text and "TrueLayer" in text
