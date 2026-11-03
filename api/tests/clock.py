"""The test run's "today" (T-08-27), taken once, as the UK day like the
app's `_today()` (T-11-9). Test modules build their dates from it, and
conftest pins the app's `_today` to it, so a run that crosses midnight sees
one day."""
from datetime import date, timedelta

from app.core.clock import uk_today

TODAY = uk_today()

# Days where "today minus a few days" leaves the month or the year (T-20-4).
# Tests whose dates depend on the calendar run on each of these, every run,
# through conftest's `today_is`, so a flaw shows on any day, not only the 1st.
CALENDAR_EDGE_DAYS = [
    date(2026, 11, 1),
    date(2026, 11, 2),
    date(2026, 11, 15),
    date(2026, 11, 30),
    date(2027, 1, 1),
    date(2028, 2, 29),
]


def earlier_this_month(today: date, days: int) -> date:
    """`days` before `today`, but never before the 1st of today's month: a
    test that means "recent, inside this month" stays in it on the 1st."""
    return max(today - timedelta(days=days), today.replace(day=1))
