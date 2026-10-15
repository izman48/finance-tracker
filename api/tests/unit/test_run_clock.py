"""One "today" for the whole run (T-08-27).

Test modules build dates from tests.clock.TODAY at import; the app asks
`_today()` as each request runs. A run that crossed midnight UTC saw two
different days (test_overdue_after_a_three_day_grace[3-False] failed).
conftest pins the app's `_today` to the run's date, everywhere it is bound.
"""
import sys
from datetime import datetime, timedelta, timezone

from app.core import clock
from app.services.analytics import common  # noqa: F401 (binds _today, as the app does)
from tests.clock import TODAY


def test_the_app_keeps_the_runs_today_after_midnight(monkeypatch):
    # The real clock moves to tomorrow (the day comes from app.core.clock
    # since T-11-9; common no longer imports datetime, T-12-8).
    monkeypatch.setattr(clock, "_now_utc", lambda: datetime.now(timezone.utc) + timedelta(days=1))
    assert clock.uk_today() != TODAY
    bound = [m for m in list(sys.modules.values()) if getattr(m, "__name__", "").startswith("app.") and hasattr(m, "_today")]
    assert bound, "no app module binds _today"
    for module in bound:
        assert module._today() == TODAY, module.__name__
