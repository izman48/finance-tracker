"""The app's "today" is the UK day (T-11-9; sec T-11-9).

One helper, `app.core.clock.uk_today`, gives the Europe/London date. Every
money path takes its day from it (through `analytics.common._today`), so
just after midnight UK time, when UTC is still on the day before, payday,
safe-to-spend and the next commitment date move with the user's calendar.
A scan fails on a new `date.today()` or UTC `.date()` in the app's services,
routers, schemas or the MCP server, with a self-test that it fires.
"""
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core import clock
from tests.conftest import _real_today

API = Path(__file__).resolve().parents[2]
SCANNED = [API / "app" / "services", API / "app" / "routers", API / "app" / "schemas", API / "mcp"]
FORBIDDEN = re.compile(
    r"date\.today\(\)|datetime\.today\(\)|utcnow\(\)\.date\(\)|date\.fromtimestamp\("
    r"|datetime\.now\([^)]*\)\.date\(\)"
)


def _freeze(monkeypatch, when: datetime):
    monkeypatch.setattr(clock, "_now_utc", lambda: when)


@pytest.mark.parametrize("utc,uk", [
    # The night the clocks go back (BST ends 25 Oct 2026, 02:00 BST).
    (datetime(2026, 10, 24, 23, 30, tzinfo=timezone.utc), date(2026, 10, 25)),
    # The last day of a BST month: UTC is still on 30 Sep.
    (datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc), date(2026, 10, 1)),
    # GMT: UK and UTC agree.
    (datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc), date(2026, 12, 31)),
    (datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc), date(2026, 10, 25)),
])
def test_uk_today_is_the_london_date(monkeypatch, utc, uk):
    _freeze(monkeypatch, utc)
    assert clock.uk_today() == uk


def test_the_apps_today_is_the_uk_day(monkeypatch):
    # conftest pins `_today` per run; the real function must follow the clock.
    _freeze(monkeypatch, datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc))
    assert _real_today() == date(2026, 10, 1)


def test_planning_date_windows_use_the_uk_day(monkeypatch):
    from pydantic import ValidationError

    from app.schemas import AddPlannedEventRequest as PlannedEventCreate
    # A frozen clock years ahead, so the window can only come from the helper.
    _freeze(monkeypatch, datetime(2030, 6, 30, 23, 30, tzinfo=timezone.utc))  # UK: 1 Jul 2030
    body = {"name": "Holiday", "amount": "500.00", "direction": "expense", "dry_run": True,
            "idempotency_key": "uk-today-0001"}
    oldest = date(2030, 7, 1) - timedelta(days=30)
    assert PlannedEventCreate(**body, date=oldest).date == oldest
    with pytest.raises(ValidationError):
        PlannedEventCreate(**body, date=oldest - timedelta(days=1))


def _violations(paths) -> list[str]:
    found = []
    for root in paths:
        files = [root] if root.is_file() else root.rglob("*.py")
        for f in files:
            if "tests" in f.parts:
                continue
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if FORBIDDEN.search(line):
                    found.append(f"{f.relative_to(API)}:{n}")
    return found


def test_no_money_path_takes_the_day_from_the_server_clock():
    for root in SCANNED:
        assert root.exists(), root  # the scan sees the real folders
    assert _violations(SCANNED) == []


@pytest.mark.parametrize("line", [
    "today = date.today()", "d = datetime.utcnow().date()", "d = datetime.now(timezone.utc).date()",
    "d = datetime.now().date()", "d = datetime.today()", "d = datetime.now(UTC).date()",
    "d = datetime.now(tz=timezone.utc).date()", "d = date.fromtimestamp(t)",
])
def test_the_scan_fires_on_a_server_clock_day(tmp_path, line):
    bad = tmp_path / "bad.py"
    bad.write_text(f"from datetime import date, datetime, timezone\n{line}\n")
    assert FORBIDDEN.search(bad.read_text())
