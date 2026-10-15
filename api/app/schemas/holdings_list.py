"""Claude's holdings view (T-11-7). The key sets are pinned by tests (sec):
nothing beyond these fields leaves the API."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Projected(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    one_year: Decimal = Field(alias="1y")
    five_years: Decimal = Field(alias="5y")
    ten_years: Decimal = Field(alias="10y")


class HoldingRow(BaseModel):
    id: str
    name: str
    kind: str
    value: Decimal
    value_as_of: date
    growth_pct: Decimal | None
    monthly_contribution: Decimal | None
    linked: bool
    projected: Projected


class HoldingList(BaseModel):
    holdings: list[HoldingRow]
    count: int
    truncated: bool
