"""Card plan API shapes (T-12-5a; sec T-12-5).

Requests allow-list the user's terms (`extra="forbid"`): no id, user, link
state or derived figure. Money is a decimal string with at most 2 dp, never
a JSON float. Bounds (sec): balance up to 10,000,000, instalments 1-120,
monthly fee £0-£1,000 and APR 0-100.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.core.display_text import visible_text

from app.schemas import _refuse_float
from app.services.analytics import common

Money = Annotated[Decimal, Field(decimal_places=2), BeforeValidator(_refuse_float)]
Balance = Annotated[Decimal, Field(gt=0, le=Decimal("10000000"), decimal_places=2), BeforeValidator(_refuse_float)]
Instalment = Annotated[Decimal, Field(gt=0, le=Decimal("10000000"), decimal_places=2), BeforeValidator(_refuse_float)]
# Pounds a month (sec nit on #230).
Fee = Annotated[Decimal, Field(ge=0, le=1000, decimal_places=2), BeforeValidator(_refuse_float)]
Apr = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2), BeforeValidator(_refuse_float)]
Name = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(visible_text)]
Count = Annotated[int, Field(ge=1, le=120, strict=True)]
# An instalment more than this far either side of today is refused as a typo.
NEXT_DATE_WINDOW = timedelta(days=366)


def _check_next_date(value: date | None) -> None:
    if value is None:
        return
    today = common._today()
    if not today - NEXT_DATE_WINDOW <= value <= today + NEXT_DATE_WINDOW:
        raise ValueError("The next instalment must be within a year of today.")


class CardPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_account_id: uuid.UUID
    name: Name
    balance: Balance
    instalment: Instalment
    fee: Fee = Decimal("0.00")
    apr: Apr | None = None
    instalments_remaining: Count
    next_date: date

    @model_validator(mode="after")
    def _dates(self) -> CardPlanCreate:
        _check_next_date(self.next_date)
        return self


class CardPlanUpdate(BaseModel):
    """Any of the terms; the card is fixed (delete and add to move a plan)."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    balance: Balance | None = None
    instalment: Instalment | None = None
    fee: Fee | None = None
    apr: Apr | None = None
    instalments_remaining: Count | None = None
    next_date: date | None = None

    @model_validator(mode="after")
    def _dates(self) -> CardPlanUpdate:
        _check_next_date(self.next_date)
        return self


class CardPlanResponse(BaseModel):
    id: uuid.UUID
    card_account_id: uuid.UUID | None
    card_name: str | None
    name: str
    balance: Decimal
    instalment: Decimal
    fee: Decimal
    instalments_remaining: int
    next_date: date | None
    final_date: date
    # Instalment + fee: what the plan adds to the card's amount due.
    monthly_total: Decimal
    # Owner D4: only a plan whose card has gone counts on its own.
    in_net_worth: bool
    # The card's provider is on the code list of providers that include
    # plans in the card balance (otherwise the UI says it isn't confirmed).
    provider_confirmed: bool
