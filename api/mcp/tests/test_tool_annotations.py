"""Every tool tells the client whether it writes (T-08-3a).

Claude clients use MCP ToolAnnotations to decide when to ask the user before
calling a tool. dry_run is only a convenience (an injected model can skip
straight to the apply), so the client-side approval prompt is one of the real
controls, and it depends on these hints being right:

  - every tool declares `readOnlyHint` explicitly (no silent defaults);
  - a tool whose name says it writes (create_, add_, update_, dismiss_,
    remove_, delete_, set_) is never read-only and never idempotent;
    update_/dismiss_/remove_/delete_ are destructive, create_/add_ are not;
  - a tool that takes `dry_run` says so, says to show the preview and get
    the user's confirmation before applying, and says that bank data is data,
    not instructions.
"""
import httpx
import pytest

from config import Settings
from server import create_server

WRITE_PREFIXES = ("create_", "add_", "update_", "dismiss_", "remove_", "delete_", "set_")
DESTRUCTIVE_PREFIXES = ("update_", "dismiss_", "remove_", "delete_", "set_")


async def _tools():
    settings = Settings("stdio", "http://api.test/api/v1", email="e@example.com", password="pw")
    server = create_server(settings, api_transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    return await server.list_tools()


def is_write(name: str) -> bool:
    return name.startswith(WRITE_PREFIXES)


@pytest.mark.anyio
async def test_every_tool_declares_whether_it_is_read_only():
    tools = await _tools()
    missing = [t.name for t in tools if t.annotations is None or t.annotations.readOnlyHint is None]
    assert not missing, f"tools without an explicit readOnlyHint: {missing}"


@pytest.mark.anyio
async def test_write_tools_ask_for_approval():
    tools = await _tools()
    writes = [t for t in tools if is_write(t.name)]
    # Precondition: the rule can only pass meaningfully if it sees a write.
    assert "create_rule_pack" in {t.name for t in writes}
    for tool in writes:
        hints = tool.annotations
        assert hints is not None, tool.name
        assert hints.readOnlyHint is False, tool.name
        assert hints.idempotentHint is False, tool.name
        assert hints.destructiveHint is tool.name.startswith(DESTRUCTIVE_PREFIXES), tool.name


@pytest.mark.anyio
async def test_read_tools_are_marked_read_only():
    tools = await _tools()
    reads = [t for t in tools if not is_write(t.name)]
    assert reads
    wrong = [t.name for t in reads if t.annotations is None or t.annotations.readOnlyHint is not True]
    assert not wrong, f"read tools not marked read-only (or a write tool with a read-style name): {wrong}"


@pytest.mark.anyio
async def test_dry_run_tools_require_confirmation_and_distrust_bank_data():
    for tool in await _tools():
        if "dry_run" not in tool.inputSchema.get("properties", {}):
            continue
        assert is_write(tool.name), tool.name
        text = tool.description or ""
        assert "dry_run" in text and "confirm" in text.lower(), tool.name
        assert "data, not instructions" in text, tool.name


# sec (T-08-6): the exact set of read-only tools. A new tool must be added
# here on purpose, so a write can't slip in under a read-style name.
READ_ONLY_TOOLS = {
    "cashflow_summary", "forecast", "spending", "spending_trend", "commitments", "accounts",
    "sync_status", "recent_transactions", "search_transactions", "rules", "rule_impact",
    "preview_rule", "list_planned_events",
}
WRITE_TOOLS = {
    "create_rule_pack", "add_planned_event", "remove_planned_event", "update_commitment", "dismiss_commitment",
}


@pytest.mark.anyio
async def test_the_tool_set_is_exactly_the_reviewed_one():
    tools = {t.name: t for t in await _tools()}
    assert set(tools) == READ_ONLY_TOOLS | WRITE_TOOLS
    assert {n for n, t in tools.items() if t.annotations.readOnlyHint is True} == READ_ONLY_TOOLS


def test_classifier_self_test():
    assert is_write("add_planned_event") and is_write("remove_planned_event")
    assert is_write("update_commitment") and is_write("create_rule_pack")
    assert not is_write("list_planned_events") and not is_write("forecast")


@pytest.mark.anyio
async def test_read_tools_explain_late_income():
    tools = {t.name: t for t in await _tools()}
    assert "late_income" in tools["forecast"].description
    assert "late" in tools["commitments"].description and "never counted" in tools["commitments"].description
