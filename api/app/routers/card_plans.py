"""Card instalment plans (T-12-5a; sec T-12-5). Web session only.

Every plan is loaded by id AND user, so another user's id gets the same 404
as an unknown one and nothing is written. The card is ownership-checked and
must be a credit card. Read-time figures come from services/card_plans.py.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ownership import owned_account, require_owned_account_ids
from app.core.security import CurrentUser
from app.models import Account, AccountRole, AccountSetting, CardPlan
from app.schemas.card_plans import CardPlanCreate, CardPlanResponse, CardPlanUpdate
from app.services import card_plans as service
from app.services.analytics import common
from app.services.analytics.common import account_role

router = APIRouter(prefix="/card-plans", tags=["card-plans"])

DB = Annotated[Session, Depends(get_db)]
# Every read works out each plan, so the rows per card are bounded (sec).
PLANS_PER_CARD_MAX = 50
# Terms a PATCH may not clear.
REQUIRED = ("name", "balance", "instalment", "fee", "instalments_remaining", "next_date")


def _own(db: Session, user_id: uuid.UUID, plan_id: uuid.UUID) -> CardPlan:
    plan = db.query(CardPlan).filter(CardPlan.id == plan_id, CardPlan.user_id == user_id).first()
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return plan


def _credit_card(db: Session, user, account_id: uuid.UUID) -> Account:
    card = owned_account(db, user, account_id)
    setting = db.query(AccountSetting).filter(
        AccountSetting.user_id == user.id, AccountSetting.account_id == card.id,
    ).first()
    if account_role(card, setting) != AccountRole.CREDIT:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="A plan belongs to a credit card.")
    return card


def _response(db: Session, plan: CardPlan) -> CardPlanResponse:
    card = db.get(Account, plan.card_account_id) if plan.card_account_id else None
    figures = service.figures(plan, common._today())
    return CardPlanResponse(
        id=plan.id, card_account_id=plan.card_account_id, card_name=card.display_name if card else None,
        name=plan.name, balance=figures.balance, instalment=plan.instalment, fee=plan.fee,
        instalments_remaining=figures.instalments_remaining, next_date=figures.next_date,
        final_date=figures.final_date, monthly_total=service.monthly_total(plan),
        in_net_worth=service.in_net_worth(plan), provider_confirmed=service.provider_confirmed(card),
    )


@router.get("", response_model=list[CardPlanResponse])
def list_plans(current_user: CurrentUser, db: DB) -> list[CardPlanResponse]:
    plans = db.query(CardPlan).filter(CardPlan.user_id == current_user.id).order_by(CardPlan.created_at).all()
    return [_response(db, p) for p in plans]


@router.post("", response_model=CardPlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(body: CardPlanCreate, current_user: CurrentUser, db: DB) -> CardPlanResponse:
    require_owned_account_ids(db, current_user, body)
    card = _credit_card(db, current_user, body.card_account_id)
    held = db.query(CardPlan).filter(CardPlan.user_id == current_user.id, CardPlan.card_account_id == card.id).count()
    if held >= PLANS_PER_CARD_MAX:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"A card can have up to {PLANS_PER_CARD_MAX} plans.")
    plan = CardPlan(user_id=current_user.id, **{**body.model_dump(), "name": body.name.strip()})
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _response(db, plan)


@router.patch("/{plan_id}", response_model=CardPlanResponse)
def update_plan(plan_id: uuid.UUID, body: CardPlanUpdate, current_user: CurrentUser, db: DB) -> CardPlanResponse:
    plan = _own(db, current_user.id, plan_id)
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(k, ...) is None for k in REQUIRED):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That term can't be cleared.")
    for field, value in changes.items():
        setattr(plan, field, value.strip() if field == "name" else value)
    db.commit()
    db.refresh(plan)
    return _response(db, plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: uuid.UUID, current_user: CurrentUser, db: DB) -> Response:
    db.delete(_own(db, current_user.id, plan_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
