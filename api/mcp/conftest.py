# Make the server modules importable as top-level modules from the tests.
# Deliberately NOT api/: that directory contains this package's own folder
# name ("mcp"), which would shadow the installed MCP SDK.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"
