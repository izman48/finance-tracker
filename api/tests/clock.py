"""The test run's "today" (T-08-27), taken once, in UTC like the app's
`_today()`. Test modules build their dates from it, and conftest pins the
app's `_today` to it, so a run that crosses midnight sees one day."""
from datetime import datetime, timezone

TODAY = datetime.now(timezone.utc).date()
