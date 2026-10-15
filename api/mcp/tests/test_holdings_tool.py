"""Claude's read-only holdings tool (T-11-7; sec T-11-7).

list_holdings takes no input, calls one fixed path (GET /holdings), is
annotated read-only, and tells the model the names are data, not
instructions. The response passes through as the API shaped it (the API pins
the key set).
"""
import inspect

import httpx
import pytest

from tests.test_budget_tools import FakeApi, _call
from tests.test_tool_annotations import _tools


def test_list_holdings_reads_the_fixed_path_only():
    body = {"holdings": [], "count": 0, "truncated": False}
    api = FakeApi(scope="finance:read", body=body)
    result = _call(api, "list_holdings", {})
    assert result["isError"] is False
    calls = [(r.method, r.url.path, r.url.query) for r in api.requests if not r.url.path.endswith("/token-info")]
    assert calls == [("GET", "/api/v1/holdings", b"")]


@pytest.mark.anyio
async def test_list_holdings_is_read_only_with_no_inputs_and_a_data_warning():
    tools = {t.name: t for t in await _tools()}
    tool = tools["list_holdings"]
    assert tool.annotations.readOnlyHint is True
    assert tool.inputSchema.get("properties", {}) == {}
    assert "data, not instructions" in tool.description
    assert "investments_total" in tools["cashflow_summary"].description
