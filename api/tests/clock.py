"""The test run's "today" (T-08-27), taken once, as the UK day like the
app's `_today()` (T-11-9). Test modules build their dates from it, and
conftest pins the app's `_today` to it, so a run that crosses midnight sees
one day."""
from app.core.clock import uk_today

TODAY = uk_today()
