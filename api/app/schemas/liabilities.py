"""Liabilities API shapes (T-10-7a; sec S-4, S-5).

Requests allow-list the user's terms only (`extra="forbid"`): the client can't
send an id, user_id, link or any derived figure. Money is a decimal string
with at most 2 dp, more than 0 and at most 1,000,000 (never a JSON float); a
mortgage's balance may be up to 10,000,000 and its APR at most 25% (sec
T-12-6).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, model_validator

from app.schemas import PLANNED_EVENT_MAX_AMOUNT, PlanningAmount, _refuse_float
from app.services.analytics import common

LiabilityKindName = Literal["loan", "finance", "bnpl", "mortgage"]
LiabilityCadenceName = Literal["monthly", "four_weekly", "fortnightly", "weekly"]
Apr = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2), BeforeValidator(_refuse_float)]
Lender = Annotated[str, Field(min_length=1, max_length=100)]
CommitmentChoice = Annotated[str, Field(min_length=1, max_length=36)]
MORTGAGE_MAX_BALANCE = Decimal("10000000")
MORTGAGE_MAX_APR = Decimal("25")
# The widest balance any kind takes; the per-kind limit is checked on the
# merged terms.
Balance = Annotated[
    Decimal, Field(gt=0, le=MORTGAGE_MAX_BALANCE, decimal_places=2), BeforeValidator(_refuse_float)
]

# Terms a PATCH may not clear (they have no "unknown" state). `payment` may
# be cleared only together with opting out; the merged check enforces that.
REQUIRED_TERMS = ("kind", "lender", "balance", "balance_as_of", "apr", "cadence", "start_date", "opted_out")
# Payments that start more than this far ahead are refused as a typo.
START_DATE_MAX_AHEAD = timedelta(days=366)


class LiabilityCreate(BaseModel):
    """A liability's terms (ux spec A6). The start date is the first payment
    and sets the payment day. Payment is required unless the user repays
    irregularly (`opted_out`)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: LiabilityKindName
    lender: Lender
    balance: Balance
    balance_as_of: date
    apr: Apr
    payment: PlanningAmount | None = None
    cadence: LiabilityCadenceName = "monthly"
    start_date: date
    end_date: date | None = None
    opted_out: StrictBool = False

    @model_validator(mode="after")
    def _check_terms(self) -> LiabilityCreate:
        today = common._today()
        if self.balance_as_of > today:
            raise ValueError("The balance date can't be in the future")
        if self.start_date > today + START_DATE_MAX_AHEAD:
            raise ValueError("The start date must be within a year from today")
        if self.end_date and self.end_date <= self.start_date:
            raise ValueError("The final payment must be after the start date")
        if self.payment is None and not self.opted_out:
            raise ValueError('Enter the payment amount, or tick "I repay this loan irregularly"')
        if self.kind != "mortgage" and self.balance > PLANNED_EVENT_MAX_AMOUNT:
            raise ValueError("The balance can be at most £1,000,000")
        if self.kind == "mortgage" and self.apr > MORTGAGE_MAX_APR:
            raise ValueError(f"A mortgage's APR can be at most {MORTGAGE_MAX_APR}%")
        return self


class LiabilityCreateRequest(LiabilityCreate):
    """Create, optionally replacing a `loan` or `other_liability` asset the
    user picked (T-10-7b). The id is checked against the caller's own assets;
    it is never matched by name or amount."""

    replaces_asset_id: uuid.UUID | None = None
    # After a 409 `choose_commitment`: one of the offered candidate ids, or
    # "new". The server re-computes the candidates and accepts nothing else.
    commitment_choice: CommitmentChoice | None = None


class LiabilityUpdate(BaseModel):
    """Only the fields sent change; the merged terms are checked as a whole."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: LiabilityKindName | None = None
    lender: Lender | None = None
    balance: Balance | None = None
    balance_as_of: date | None = None
    apr: Apr | None = None
    payment: PlanningAmount | None = None
    cadence: LiabilityCadenceName | None = None
    start_date: date | None = None
    end_date: date | None = None
    opted_out: StrictBool | None = None
    # Opting back in: as on create.
    commitment_choice: CommitmentChoice | None = None

    @model_validator(mode="after")
    def _no_cleared_terms(self) -> LiabilityUpdate:
        cleared = [f for f in REQUIRED_TERMS if f in self.model_fields_set and getattr(self, f) is None]
        if cleared:
            raise ValueError(f"These can't be cleared: {', '.join(cleared)}")
        return self


class LiabilityResponse(BaseModel):
    id: uuid.UUID
    kind: str
    lender: str
    balance: Decimal
    balance_as_of: date
    apr: Decimal
    payment: Decimal | None
    cadence: str
    start_date: date
    end_date: date | None
    opted_out: bool
    # Derived on read, never stored. The schedule figures are null when the
    # user repays irregularly (they would be guesses).
    current_balance: Decimal
    next_payment_date: date | None
    payments_remaining: int | None
    payoff_date: date | None
    interest_remaining: Decimal | None
    total_cost: Decimal | None
    # Linked and every scheduled payment has been made.
    paid_off: bool
    # The as-of date is more than 90 days old: ask the user to update it.
    balance_stale: bool
    # The commitment carrying the repayment (T-10-8), or null.
    linked_commitment: LinkedCommitment | None
    # On a create or edit that linked one: "created" (a new bill) or
    # "linked" (an existing bill was taken over); null otherwise.
    link_result: Literal["created", "linked"] | None = None


class LinkedCommitment(BaseModel):
    id: uuid.UUID
    label: str


class OverpaymentResponse(BaseModel):
    """A lump sum paid off today, payment unchanged (T-10-11). Read-only."""

    lump_sum: Decimal
    # Paying the whole loan off today: the balance plus up to 58 days' interest.
    settlement_figure: Decimal
    settlement_interest: Decimal
    payments_before: int
    payments_after: int
    payments_saved: int
    interest_before: Decimal
    interest_after: Decimal
    interest_saved: Decimal
    payoff_date_before: date
    payoff_date_after: date | None
    # A plain fact, never a recommendation (no advice).
    note: str
