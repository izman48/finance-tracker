"""Cashflow analytics endpoints: summary, commitments review, account settings."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models import (
    Account,
    AccountSetting,
    CommitmentRule,
    CommitmentSource,
    CommitmentStatus,
    PlannedItem,
)
from app.schemas import (
    AccountSettingUpdate,
    CashflowSummary,
    CommitmentCreate,
    CommitmentFromTransaction,
    CommitmentResponse,
    CommitmentUpdate,
    ForecastResponse,
    NetWorthPoint,
    PlannedItemCreate,
    PlannedItemResponse,
    SpendingResponse,
    SpendingTrendResponse,
)
from datetime import date
from app.services import analytics_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=CashflowSummary)
def get_summary(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CashflowSummary:
    """Dashboard cashflow summary: safe-to-spend, available cash, owed, etc."""
    return CashflowSummary(**analytics_service.get_summary(db, current_user))


@router.get("/net-worth-history", response_model=list[NetWorthPoint])
def get_net_worth_history(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    months: int = 12,
) -> list[NetWorthPoint]:
    """Net worth at month-ends (bank balances reconstructed + manual assets)."""
    months = max(1, min(months, 60))
    return [
        NetWorthPoint(**point)
        for point in analytics_service.net_worth_history(db, current_user, months)
    ]


@router.get("/forecast", response_model=ForecastResponse)
def get_forecast(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    horizon: str = "payday",
) -> ForecastResponse:
    """Balance-over-time projection across the horizon (payday|month|30|60|90)."""
    return ForecastResponse(**analytics_service.get_forecast(db, current_user, horizon))


@router.get("/spending", response_model=SpendingResponse)
def get_spending(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    period: str = "since_payday",
    frm: date | None = None,
    to: date | None = None,
    exclude_commitments: bool = False,
) -> SpendingResponse:
    """Spending breakdown for a period (since_payday|this_month|last_30|custom)."""
    return SpendingResponse(
        **analytics_service.get_spending(db, current_user, period, frm, to, exclude_commitments)
    )


@router.get("/spending/trend", response_model=SpendingTrendResponse)
def get_spending_trend(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    months: int = 6,
    exclude_commitments: bool = False,
) -> SpendingTrendResponse:
    """Real spending per month over the last `months` months (noise excluded)."""
    return SpendingTrendResponse(
        **analytics_service.get_spending_trend(db, current_user, months, exclude_commitments)
    )


@router.get("/commitments", response_model=list[CommitmentResponse])
def list_commitments(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[CommitmentRule]:
    """Detected + user commitments to review. Refreshes suggestions first."""
    analytics_service.sync_suggestions(db, current_user)
    return (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == current_user.id,
            CommitmentRule.status != CommitmentStatus.DISMISSED.value,
        )
        .order_by(CommitmentRule.direction, CommitmentRule.next_date)
        .all()
    )


@router.post("/commitments/from-transaction", response_model=CommitmentResponse, status_code=status.HTTP_201_CREATED)
def commitment_from_transaction(
    data: CommitmentFromTransaction,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CommitmentRule:
    """Mark a transaction as recurring → a confirmed commitment."""
    rule = analytics_service.commitment_from_transaction(
        db, current_user, str(data.transaction_id), data.cadence
    )
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return rule


@router.post("/commitments", response_model=CommitmentResponse, status_code=status.HTTP_201_CREATED)
def create_commitment(
    data: CommitmentCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CommitmentRule:
    """Manually add a commitment (confirmed immediately)."""
    rule = CommitmentRule(
        user_id=current_user.id,
        direction=data.direction,
        label=data.label,
        amount=data.amount,
        cadence=data.cadence,
        interval_days=data.interval_days,
        interval_months=data.interval_months,
        next_date=data.next_date,
        account_id=data.account_id,
        source=CommitmentSource.MANUAL.value,
        status=CommitmentStatus.CONFIRMED.value,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/commitments/{commitment_id}", response_model=CommitmentResponse)
def update_commitment(
    commitment_id: str,
    data: CommitmentUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CommitmentRule:
    """Confirm/dismiss or edit a commitment."""
    rule = (
        db.query(CommitmentRule)
        .filter(CommitmentRule.id == commitment_id, CommitmentRule.user_id == current_user.id)
        .first()
    )
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commitment not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/planned-items", response_model=list[PlannedItemResponse])
def list_planned_items(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[PlannedItem]:
    return (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == current_user.id, PlannedItem.active.is_(True))
        .order_by(PlannedItem.start_date)
        .all()
    )


@router.post("/planned-items", response_model=PlannedItemResponse, status_code=status.HTTP_201_CREATED)
def create_planned_item(
    data: PlannedItemCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PlannedItem:
    item = PlannedItem(user_id=current_user.id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/planned-items/{item_id}")
def delete_planned_item(
    item_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    item = (
        db.query(PlannedItem)
        .filter(PlannedItem.id == item_id, PlannedItem.user_id == current_user.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned item not found")
    db.delete(item)
    db.commit()
    return {"success": True}


@router.patch("/accounts/{account_id}/settings")
def update_account_settings(
    account_id: str,
    data: AccountSettingUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Upsert an account's cashflow settings (role, overdraft, repayment config)."""
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == current_user.id)
        .first()
    )
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    setting = (
        db.query(AccountSetting)
        .filter(AccountSetting.account_id == account.id)
        .first()
    )
    if not setting:
        setting = AccountSetting(
            user_id=current_user.id,
            account_id=account.id,
            role=analytics_service.default_role(account),
        )
        db.add(setting)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(setting, field, value)
    db.commit()

    return {"success": True, "message": "Account settings updated"}
