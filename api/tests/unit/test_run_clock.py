"""One "today" for the whole run (T-08-27).

Test modules build dates from tests.clock.TODAY at import; the app asks
`_today()` as each request runs. A run that crossed midnight UTC saw two
different days (test_overdue_after_a_three_day_grace[3-False] failed).
conftest pins the app's `_today` to the run's date, everywhere it is bound.
"""
import sys
from datetime import datetime, timedelta, timezone

from app.services.analytics import common
from tests.clock import TODAY


def test_the_app_keeps_the_runs_today_after_midnight(monkeypatch):
    class Tomorrow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc) + timedelta(days=1)

    monkeypatch.setattr(common, "datetime", Tomorrow)
    bound = [m for m in list(sys.modules.values()) if getattr(m, "__name__", "").startswith("app.") and hasattr(m, "_today")]
    assert bound, "no app module binds _today"
    for module in bound:
        assert module._today() == TODAY, module.__name__
