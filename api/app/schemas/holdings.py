"""Holding contribution API shapes (T-11-3c; sec on #203).

The request allow-lists the user's choice and terms (`extra="forbid"`): the
server sets the link's user, role, `commitment_created` and start date, and
the bill's cadence (monthly). Money is a decimal string, 2 dp, more than 0
and at most 10,000,000 (sec T-11-4 bounds), never a JSON float.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.schemas import _refuse_float
from app.schemas.liabilities import CommitmentChoice, LinkedCommitment
from app.services.analytics import common

Contribution = Annotated[
    Decimal, Field(gt=0, le=Decimal("10000000"), decimal_places=2), BeforeValidator(_refuse_float),
]


class ContributionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Contribution
    # The next payment day; it sets the monthly payment day.
    next_date: date
    # Absent: link a new bill unless one could be this (then 409 with the
    # candidates). "new" or a candidate id: the user's pick (D2).
    commitment_choice: CommitmentChoice | None = None
    # The account the bill leaves (ownership-checked; the UI offers current
    # accounts). Absent on an edit: unchanged.
    pay_from_account_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _next_date_within_a_year(self) -> ContributionRequest:
        today = common._today()
        if not today <= self.next_date <= today + timedelta(days=366):
            raise ValueError("The next payment must be between today and a year from now.")
        return self


class ContributionResponse(BaseModel):
    linked_commitment: LinkedCommitment
    link_result: Literal["created", "linked", "updated"]
