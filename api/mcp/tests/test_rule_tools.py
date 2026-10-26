"""Claude's rule edit tool.

update_rule needs the finance:rules.edit scope (a second layer; the API
enforces it), addresses a rule by its UUID only, and sends only the fields
the model passed. clear_counts_as sends an explicit null. API errors become
short fixed messages.
"""
import json

import httpx
import pytest
from starlette.testclient import TestClient

from config import Settings
from server import create_server

PUBLIC = "https://example.com"
RESOURCE = f"{PUBLIC}/mcp"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
RULE_ID = "11111111-2222-3333-4444-555555555555"
KEY = "key-00000001"


class FakeApi:
    def __init__(self, scope="finance:read finance:rules.edit", status=200, body=None):
        self.scope, self.status = scope, status
        self.body = {"dry_run": True, "changes": []} if body is None else body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/oauth/token-info"):
            return httpx.Response(200, json={"active": True, "client_id": "c", "scope": self.scope, "aud": RESOURCE})
        return httpx.Response(self.status, json=self.body)

    def calls(self):
        return [(r.method, r.url.path, json.loads(r.content) if r.content else None)
                for r in self.requests if "/rules" in r.url.path]


def _call(api, arguments, name="update_rule"):
    settings = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": PUBLIC})
    app = create_server(settings, api_transport=httpx.MockTransport(api)).streamable_http_app()
    with TestClient(app, base_url=PUBLIC) as c:
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": name, "arguments": arguments}},
                   headers={**MCP_HEADERS, "Authorization": "Bearer good"})
    return r.json()["result"]


def _text(result) -> str:
    return result["content"][0]["text"]


def test_update_rule_previews_by_default_and_sends_only_passed_fields():
    api = FakeApi()
    result = _call(api, {"rule_id": RULE_ID, "idempotency_key": KEY, "category": "Transport"})
    assert result["isError"] is False
    assert api.calls() == [("POST", f"/api/v1/planning/rules/{RULE_ID}/update",
                            {"idempotency_key": KEY, "dry_run": True, "category": "Transport"})]


def test_update_rule_sends_every_editable_field():
    api = FakeApi()
    _call(api, {"rule_id": RULE_ID, "idempotency_key": KEY, "pattern": "TESCO PFS", "match_type": "contains",
                "match_field": "description", "category": "Transport", "counts_as": "spending",
                "enabled": False, "dry_run": False})
    [(_, _, body)] = api.calls()
    assert body == {"idempotency_key": KEY, "dry_run": False, "pattern": "TESCO PFS", "match_type": "contains",
                    "match_field": "description", "category": "Transport", "counts_as": "spending",
                    "enabled": False}


def test_clear_counts_as_sends_an_explicit_null():
    api = FakeApi()
    _call(api, {"rule_id": RULE_ID, "idempotency_key": KEY, "clear_counts_as": True})
    [(_, _, body)] = api.calls()
    assert "counts_as" in body and body["counts_as"] is None


def test_counts_as_and_clear_counts_as_together_is_refused():
    api = FakeApi()
    result = _call(api, {"rule_id": RULE_ID, "idempotency_key": KEY, "counts_as": "transfer",
                         "clear_counts_as": True})
    assert result["isError"] is True
    assert api.calls() == []


@pytest.mark.parametrize("bad", ["TESCO", "../../audit/x/undo", ""])
def test_a_rule_is_addressed_by_its_uuid_only(bad):
    api = FakeApi()
    result = _call(api, {"rule_id": bad, "idempotency_key": KEY, "category": "Transport"})
    assert result["isError"] is True
    assert api.calls() == []


def test_without_the_edit_scope_nothing_is_called():
    """rules.write (add packs) is not enough to edit existing rules."""
    api = FakeApi(scope="finance:read finance:rules.write")
    result = _call(api, {"rule_id": RULE_ID, "idempotency_key": KEY, "category": "Transport"})
    assert result["isError"] is True and "finance:rules.edit" in _text(result)
    assert api.calls() == []


@pytest.mark.parametrize("status,body,expected", [
    (404, {"detail": "Rule not found"}, "no rule of yours"),
    (403, {"detail": "x"}, "permission to edit rules"),
    (400, {"detail": "Invalid or unsupported regex: nilu matches with a linear-time engine, so back-references, "
                     "look-arounds and conditional groups aren't allowed"}, "back-references"),
    (409, {"detail": "This idempotency_key was already used for a different request."}, "already used"),
    (409, {"detail": "This change would recategorise more than 5,000 transactions. Make it on the Rules page."},
     "Make it on the Rules page"),
])
def test_api_errors_become_short_messages(status, body, expected):
    api = FakeApi(status=status, body=body)
    result = _call(api, {"rule_id": RULE_ID, "idempotency_key": KEY, "category": "Transport"})
    assert result["isError"] is True and expected in _text(result)


def test_the_tool_text_names_the_cap_and_the_rules_page():
    """T-16-3: Claude can tell the user before asking for confirmation."""
    import anyio

    from config import Settings as S

    async def description():
        settings = S("stdio", "http://api.test/api/v1", email="e@example.com", password="pw")
        server = create_server(settings, api_transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        return next(t.description for t in await server.list_tools() if t.name == "update_rule")
    text = anyio.run(description)
    assert "5,000" in text and "over_cap" in text
    assert "Rules page" in text and "/rules" in text
