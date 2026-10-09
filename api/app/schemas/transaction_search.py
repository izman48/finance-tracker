"""Request and response for POST /banking/transactions/search.

A JSON body rather than query parameters keeps the search term (merchant
names are personal financial data) out of access logs.
"""
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import TransactionResponse
from app.services.transaction_search import (
    DEFAULT_WINDOW_DAYS,
    MAX_QUERY,
    MAX_WINDOW_DAYS,
    MIN_QUERY,
    london_today,
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TransactionSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    frm: date | None = None
    to: date | None = None
    include_transfers: bool = False
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(50, ge=1, le=100)

    @field_validator("query")
    @classmethod
    def _literal_text(cls, v: str) -> str:
        v = v.strip()
        if not MIN_QUERY <= len(v) <= MAX_QUERY:
            raise ValueError(f"must be {MIN_QUERY}-{MAX_QUERY} characters")
        if any(unicodedata.category(c) == "Cc" for c in v):
            raise ValueError("must not contain control characters")
        return v

    @field_validator("frm", "to", mode="before")
    @classmethod
    def _iso_only(cls, v: Any) -> Any:
        if v is not None and not (isinstance(v, str) and _ISO_DATE.match(v)):
            raise ValueError("must be a date as YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def _window(self) -> "TransactionSearchRequest":
        if self.to is None:
            self.to = self.frm + timedelta(days=DEFAULT_WINDOW_DAYS) if self.frm else london_today()
        if self.frm is None:
            self.frm = self.to - timedelta(days=DEFAULT_WINDOW_DAYS)
        if self.frm > self.to:
            raise ValueError("frm must be on or before to")
        if (self.to - self.frm).days > MAX_WINDOW_DAYS:
            raise ValueError(f"the range can span at most {MAX_WINDOW_DAYS} days")
        return self


class TransactionSearchResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    # Sum over every match on every page: debits add, credits (refunds) subtract.
    total_amount: Decimal
    page: int
    page_size: int
    frm: date
    to: date
