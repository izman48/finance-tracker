"""Liabilities the user enters by hand (T-10-7a): loans, finance, BNPL.

Web session only. Every record is loaded by id AND user, so another user's id
gets the same 404 as an unknown one and nothing is written. Derived figures
are computed on read (services/liabilities.py). A liability with a payment
carries its repayment as one linked commitment (T-10-8,
services/liability_links.py), written in the same transaction.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models import Asset, CommitmentRule, Liability
from app.schemas.liabilities import (
    LiabilityCreate,
    LiabilityCreateRequest,
    LiabilityResponse,
    LiabilityUpdate,
    LinkedCommitment,
)
from app.services import liabilities as service
from app.services import liability_links as links
from app.services.analytics import common

router = APIRouter(prefix="/liabilities", tags=["liabilities"])

DB = Annotated[Session, Depends(get_db)]
TERMS = tuple(LiabilityCreate.model_fields)
# Every list read amortises each row, so the rows per user are bounded.
LIABILITIES_PER_USER_MAX = 50
# Asset types a liability can replace. A mortgage isn't a kind yet (ux A8).
CONVERTIBLE_ASSET_TYPES = ("loan", "other_liability")


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


def _response(
    liability: Liability, rule: CommitmentRule | None, link_result: links.LinkResult | None = None,
) -> LiabilityResponse:
    terms = {field: getattr(liability, field) for field in TERMS}
    return LiabilityResponse(
        id=liability.id, **terms, **service.derived_figures(liability, common._today()),
        linked_commitment=LinkedCommitment(id=rule.id, label=rule.label) if rule is not None else None,
        link_result=link_result,
    )


def _link(db: Session, liability: Liability, choice: str | None) -> links.LinkResult:
    """Link the repayment, or 409 `choose_commitment` with the candidates."""
    try:
        return links.link(db, liability, choice, common._today())
    except links.ChooseCommitment as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "code": "choose_commitment",
            "message": "You already have more than one bill that could be this payment. Choose one.",
            "candidates": [
                {
                    "id": str(r.id), "label": r.label, "amount": str(r.amount), "cadence": r.cadence,
                    "interval_days": r.interval_days, "next_date": r.next_date.isoformat(),
                }
                for r in exc.candidates
            ],
        })


def _commit(db: Session) -> None:
    """One liability per commitment (DB constraint): a concurrent link of the
    same bill is a 409, never a second link."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That bill was just linked to another loan. Reload and try again.",
        ) from None


@router.get("", response_model=list[LiabilityResponse])
def list_liabilities(current_user: CurrentUser, db: DB) -> list[LiabilityResponse]:
    """Highest APR first, then highest balance, then lender A to Z (ux L-1).
    These columns are encrypted, so the sort happens here, not in SQL."""
    rows = db.query(Liability).filter(Liability.user_id == current_user.id).all()
    rows.sort(key=lambda x: (-x.apr, -x.balance, x.lender.casefold()))
    rules = {r.id: r for r in db.query(CommitmentRule).filter(CommitmentRule.user_id == current_user.id)}
    return [_response(x, rules.get(x.linked_commitment_id) if x.linked_commitment_id else None) for x in rows]


@router.post("", response_model=LiabilityResponse, status_code=status.HTTP_201_CREATED)
def create_liability(body: LiabilityCreateRequest, current_user: CurrentUser, db: DB) -> LiabilityResponse:
    """Create a liability. With `replaces_asset_id`, the same transaction
    deletes that asset, so the debt is counted once. A second call with the
    same id finds no asset (404) and creates nothing."""
    held = db.query(Liability).filter(Liability.user_id == current_user.id).count()
    if held >= LIABILITIES_PER_USER_MAX:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You can track up to {LIABILITIES_PER_USER_MAX} loans. Delete one to add another.",
        )
    replaced = _replaceable_asset(db, current_user.id, body.replaces_asset_id) if body.replaces_asset_id else None
    _check_schedule_clears(body)
    liability = Liability(user_id=current_user.id, **body.model_dump(exclude={"replaces_asset_id", "commitment_choice"}))
    db.add(liability)
    result = None if liability.opted_out else _link(db, liability, body.commitment_choice)
    if replaced is not None:
        db.delete(replaced)
    _commit(db)
    db.refresh(liability)
    return _response(liability, links.linked_rule(db, liability), result)


def _replaceable_asset(db: Session, user_id: uuid.UUID, asset_id: uuid.UUID) -> Asset:
    """The caller's own loan-type asset, locked until this transaction ends so
    two concurrent conversions can't both create a liability."""
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.user_id == user_id)
        .with_for_update()
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.asset_type not in CONVERTIBLE_ASSET_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only a loan or other debt on your balance sheet can be replaced.",
        )
    return asset


@router.get("/{liability_id}", response_model=LiabilityResponse)
def get_liability(liability_id: uuid.UUID, current_user: CurrentUser, db: DB) -> LiabilityResponse:
    liability = _own(db, current_user.id, liability_id)
    return _response(liability, links.linked_rule(db, liability))


@router.patch("/{liability_id}", response_model=LiabilityResponse)
def update_liability(
    liability_id: uuid.UUID, body: LiabilityUpdate, current_user: CurrentUser, db: DB
) -> LiabilityResponse:
    """Edit the terms. The linked commitment follows (rule 4); opting out
    removes it (rule 3); opting back in links one like a create."""
    liability = _own(db, current_user.id, liability_id)
    updates = body.model_dump(exclude_unset=True)
    choice = updates.pop("commitment_choice", None)
    merged = {field: getattr(liability, field) for field in TERMS} | updates
    try:
        terms = LiabilityCreate.model_validate(merged)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors())
    _check_schedule_clears(terms)
    was_linked = liability.linked_commitment_id is not None
    for field, value in terms.model_dump().items():
        setattr(liability, field, value)
    result: links.LinkResult | None = None
    if terms.opted_out and was_linked:
        links.remove(db, liability)
    elif not terms.opted_out and not was_linked and "opted_out" in updates:
        result = _link(db, liability, choice)
    elif was_linked:
        rule = links.linked_rule(db, liability)
        if rule is not None:
            links.sync(liability, rule, common._today())
    _commit(db)
    db.refresh(liability)
    return _response(liability, links.linked_rule(db, liability), result)


@router.delete("/{liability_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_liability(liability_id: uuid.UUID, current_user: CurrentUser, db: DB) -> Response:
    """Without an opt-out first, the linked commitment stays as an ordinary
    bill (owner D4)."""
    liability = _own(db, current_user.id, liability_id)
    links.release(db, liability)
    db.delete(liability)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
