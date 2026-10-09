"""Exact transaction search: literal text matching and London-day windows.

Merchant and description are encrypted, so matching happens in Python on
decrypted rows. The query is never compiled into a regex or SQL: it is a
literal, case-insensitive substring, plus one fixed normalisation applied to
both sides so descriptor variants ("TESCO STORES 3297", "TESCO*STORES") match.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
DEFAULT_WINDOW_DAYS = 90
MAX_WINDOW_DAYS = 731
MIN_QUERY, MAX_QUERY = 2, 100

_NOT_WORD = re.compile(r"[^0-9a-z]+")
_DIGITS = re.compile(r"^\d+$")


def normalise(text: str) -> str:
    """Case-fold, punctuation to spaces, digit-only tokens dropped, spaces
    collapsed. Fixed, not user-supplied, so it cannot act as a pattern."""
    tokens = _NOT_WORD.sub(" ", text.casefold()).split()
    return " ".join(t for t in tokens if not _DIGITS.match(t))


def matcher(query: str):
    """A predicate for the (already validated, stripped) query."""
    literal = query.casefold()
    normalised = normalise(query)
    use_normalised = len(normalised) >= MIN_QUERY

    def matches(*fields: str | None) -> bool:
        haystack = " ".join(f for f in fields if f)
        if literal in haystack.casefold():
            return True
        return use_normalised and f" {normalised} " in f" {normalise(haystack)} "

    return matches


def london_today() -> date:
    return datetime.now(LONDON).date()


def utc_bounds(frm: date, to: date) -> tuple[datetime, datetime]:
    """[start, end) in UTC covering London days frm..to inclusive."""
    start = datetime.combine(frm, time.min, LONDON).astimezone(timezone.utc)
    end = datetime.combine(to + timedelta(days=1), time.min, LONDON).astimezone(timezone.utc)
    return start, end
