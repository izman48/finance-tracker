"""The MCP server never takes "today" from the server clock (T-11-9; sec).

The API owns the UK day (`app.core.clock.uk_today`); the MCP server passes
dates through and computes none. This scan fails on a new `date.today()` or
UTC `.date()` in the server's own files, with a self-test that it fires. It
lives here because the MCP server has its own image (the API image has no
`mcp/`).
"""
import re
from pathlib import Path

import pytest

MCP = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(
    r"date\.today\(\)|datetime\.today\(\)|utcnow\(\)\.date\(\)|date\.fromtimestamp\("
    r"|datetime\.now\([^)]*\)\.date\(\)"
)


def _sources() -> list[Path]:
    return [f for f in MCP.glob("*.py") if f.is_file()]


def test_the_scan_sees_the_server():
    names = {f.name for f in _sources()}
    assert "server.py" in names and "api_client.py" in names


def test_no_mcp_code_takes_the_day_from_the_server_clock():
    hits = [f"{f.name}:{n}" for f in _sources() for n, line in enumerate(f.read_text().splitlines(), 1)
            if FORBIDDEN.search(line)]
    assert hits == []


@pytest.mark.parametrize("line", [
    "today = date.today()", "d = datetime.utcnow().date()", "d = datetime.now(timezone.utc).date()",
    "d = datetime.now().date()", "d = datetime.today()", "d = date.fromtimestamp(t)",
])
def test_the_scan_fires_on_a_server_clock_day(line):
    assert FORBIDDEN.search(line)
