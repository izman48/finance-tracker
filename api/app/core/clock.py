"""The app's "today" is the UK day (T-11-9; sec T-11-9).

Payday, safe-to-spend, commitment dates and every date window follow the
user's calendar, and nilu's users are in the UK. Between midnight and 01:00
during British Summer Time, UTC is still on the day before, so a UTC date
would put payday or a bill on the wrong day. Everything takes its day from
`uk_today()`; timestamps stay in UTC.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def uk_today() -> date:
    """Today's date in Europe/London (BST or GMT as the calendar says)."""
    return _now_utc().astimezone(LONDON).date()
