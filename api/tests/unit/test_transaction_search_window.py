"""Default search window when only one end is given (T-07-6)."""
from datetime import date, timedelta

from app.schemas.transaction_search import TransactionSearchRequest


def test_frm_only_never_ends_in_the_future(monkeypatch):
    monkeypatch.setattr("app.schemas.transaction_search.london_today", lambda: date(2026, 10, 10))
    recent = TransactionSearchRequest(query="tesco", frm="2026-09-01")
    assert recent.window() == (date(2026, 9, 1), date(2026, 10, 10))
    old = TransactionSearchRequest(query="tesco", frm="2026-01-01")
    assert old.window() == (date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=90))
