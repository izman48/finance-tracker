"""Liabilities the user enters by hand (T-10-7a): loans, finance, BNPL.

Web session only. Every record is loaded by id AND user, so another user's id
gets the same 404 as an unknown one and nothing is written. Derived figures
are computed on read (services/liabilities.py).
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models import Liability
from app.schemas.liabilities import LiabilityCreate, LiabilityResponse, LiabilityUpdate
from app.services import liabilities as service
from app.services.analytics import common

router = APIRouter(prefix="/liabilities", tags=["liabilities"])

DB = Annotated[Session, Depends(get_db)]
TERMS = tuple(LiabilityCreate.model_fields)
# Every list read amortises each row, so the rows per user are bounded.
LIABILITIES_PER_USER_MAX = 50


def _own(db: Session, user_id: uuid.UUID, liability_id: uuid.UUID) -> Liability:
    liability = (
        db.query(Liability)
        .filter(Liability.id == liability_id, Liability.user_id == user_id)
        .first()
    )
    if liability is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liability not found")
    return liability


def _check_schedule_clears(terms: LiabilityCreate) -> None:
    if terms.opted_out or terms.payment is None:  # no payment only when opted out
        return
    first = service.next_payment_on(terms.start_date, terms.cadence, terms.balance_as_of, common._today())
    try:
        service.amortise(terms.balance, terms.apr, terms.payment, first, terms.cadence)
    except service.PaymentTooLow as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)


def _response(liability: Liability) -> LiabilityResponse:
    terms = {field: getattr(liability, field) for field in TERMS}
    return LiabilityResponse(
        id=liability.id, **terms, **service.derived_figures(liability, common._today())
    )


@router.get("", response_model=list[LiabilityResponse])
def list_liabilities(current_user: CurrentUser, db: DB) -> list[LiabilityResponse]:
    """Highest APR first, then highest balance, then lender A to Z (ux L-1).
    These columns are encrypted, so the sort happens here, not in SQL."""
    rows = db.query(Liability).filter(Liability.user_id == current_user.id).all()
    rows.sort(key=lambda x: (-x.apr, -x.balance, x.lender.casefold()))
    return [_response(x) for x in rows]


@router.post("", response_model=LiabilityResponse, status_code=status.HTTP_201_CREATED)
def create_liability(body: LiabilityCreate, current_user: CurrentUser, db: DB) -> LiabilityResponse:
    held = db.query(Liability).filter(Liability.user_id == current_user.id).count()
    if held >= LIABILITIES_PER_USER_MAX:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You can track up to {LIABILITIES_PER_USER_MAX} loans. Delete one to add another.",
        )
    _check_schedule_clears(body)
    liability = Liability(user_id=current_user.id, **body.model_dump())
    db.add(liability)
    db.commit()
    db.refresh(liability)
    return _response(liability)


@router.get("/{liability_id}", response_model=LiabilityResponse)
def get_liability(liability_id: uuid.UUID, current_user: CurrentUser, db: DB) -> LiabilityResponse:
    return _response(_own(db, current_user.id, liability_id))


@router.patch("/{liability_id}", response_model=LiabilityResponse)
def update_liability(
    liability_id: uuid.UUID, body: LiabilityUpdate, current_user: CurrentUser, db: DB
) -> LiabilityResponse:
    liability = _own(db, current_user.id, liability_id)
    updates = body.model_dump(exclude_unset=True)
    merged = {field: getattr(liability, field) for field in TERMS} | updates
    try:
        terms = LiabilityCreate.model_validate(merged)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors())
    _check_schedule_clears(terms)
    for field, value in terms.model_dump().items():
        setattr(liability, field, value)
    db.commit()
    db.refresh(liability)
    return _response(liability)


@router.delete("/{liability_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_liability(liability_id: uuid.UUID, current_user: CurrentUser, db: DB) -> Response:
    db.delete(_own(db, current_user.id, liability_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
