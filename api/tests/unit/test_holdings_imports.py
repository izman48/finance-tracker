"""Each holdings module imports on its own (T-12-8; eng-b on #210).

`import app.services.holdings.inputs` alone used to fail with a circular
import through `app.services.analytics.__init__`. It worked only in the
app's import order, so a script, a worker or a new test importing it first
would break. Each runs in a fresh interpreter, so no earlier import hides it.
"""
import subprocess
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("module", [
    "app.services.holdings.inputs",
    "app.services.holdings.projection",
    "app.services.holdings.registry",
    "app.services.holding_links",
])
def test_the_module_imports_first(module):
    result = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=API_DIR, capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-2000:]
