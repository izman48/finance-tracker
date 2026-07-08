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
    RepaymentScheduleItem,
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
    PlanFromTransaction,
    PlannedItemCreate,
    PlannedItemResponse,
    ProjectionResponse,
    RepaymentScheduleItemCreate,
    RepaymentScheduleItemResponse,
    SpendingResponse,
    SpendingTransaction,
    SpendingTrendResponse,
)
from datetime import date
from decimal import Decimal

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


@router.get("/net-worth-projection", response_model=ProjectionResponse)
def get_net_worth_projection(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    target_amount: Decimal | None = None,
    monthly_contribution: Decimal = Decimal(0),
    annual_growth_pct: Decimal = Decimal("5"),
) -> ProjectionResponse:
    """Project net worth forward from stated assumptions (compound growth +
    monthly contributions). A factual calculation with the assumptions echoed
    back — an estimate, not advice."""
    return ProjectionResponse(
        **analytics_service.net_worth_projection(
            db, current_user,
            target_amount=target_amount,
            monthly_contribution=monthly_contribution,
            annual_growth_pct=annual_growth_pct,
        )
    )


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
    lens: str = "money_out",
    hide_transfers: bool = False,
    hide_card_payments: bool = False,
    account_id: str | None = None,
    kind: str | None = None,
) -> SpendingResponse:
    """Spending breakdown for a period (since_payday|this_month|last_30|custom).

    lens: 'money_out' (default — cash that left your bank, reconciles to a
    statement) or 'purchases' (spend booked at purchase time).

    account_id/kind scope the category + merchant breakdown to the active drill
    (an account, or the cash/credit side) without changing the period figures.
    """
    return SpendingResponse(
        **analytics_service.get_spending(
            db, current_user, period, frm, to, exclude_commitments,
            lens=lens, hide_transfers=hide_transfers, hide_card_payments=hide_card_payments,
            account_id=account_id, kind=kind,
        )
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


@router.get("/spending/transactions", response_model=list[SpendingTransaction])
def get_spending_transactions(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    period: str = "since_payday",
    frm: date | None = None,
    to: date | None = None,
    exclude_commitments: bool = False,
    category: str | None = None,
    merchant: str | None = None,
    kind: str | None = None,
) -> list[SpendingTransaction]:
    """The individual transactions behind a spending figure — drill into a
    category, a merchant, or the cash/credit split."""
    return [
        SpendingTransaction(**t)
        for t in analytics_service.spending_transactions(
            db, current_user, period, frm, to, exclude_commitments, category, merchant, kind
        )
    ]


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
        match_key=analytics_service.merchant_match_key(data.direction, data.match_merchant),
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

    updates = data.model_dump(exclude_unset=True)
    # match_merchant is a virtual field — translate it into the stored match_key.
    if "match_merchant" in updates:
        merchant = updates.pop("match_merchant")
        direction = updates.get("direction") or rule.direction
        rule.match_key = analytics_service.merchant_match_key(direction, merchant)
    for field, value in updates.items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/commitments/{commitment_id}/skip", response_model=CommitmentResponse)
def skip_commitment(
    commitment_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CommitmentRule:
    """Skip the next occurrence (e.g. paid early) — advances it one cadence step."""
    rule = analytics_service.skip_commitment(db, current_user, commitment_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commitment not found")
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


@router.post(
    "/planned/from-transaction",
    response_model=PlannedItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def plan_from_transaction(
    data: PlanFromTransaction,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PlannedItem:
    """Convert a purchase into a payment plan ("pay on finance"). Excludes the
    original transaction from spending; the installments show in the forecast."""
    item = analytics_service.convert_transaction_to_plan(
        db, current_user, str(data.transaction_id), data.months, data.monthly_amount, data.start_date
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
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


def _owned_account(db: Session, user, account_id: str) -> Account:
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == user.id)
        .first()
    )
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


@router.get("/accounts/{account_id}/repayments", response_model=list[RepaymentScheduleItemResponse])
def list_repayments(
    account_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[RepaymentScheduleItem]:
    """Scheduled repayments for a credit account (for the `scheduled` strategy)."""
    _owned_account(db, current_user, account_id)
    return (
        db.query(RepaymentScheduleItem)
        .filter(
            RepaymentScheduleItem.user_id == current_user.id,
            RepaymentScheduleItem.account_id == account_id,
        )
        .order_by(RepaymentScheduleItem.due_date)
        .all()
    )


@router.post(
    "/accounts/{account_id}/repayments",
    response_model=RepaymentScheduleItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_repayment(
    account_id: str,
    data: RepaymentScheduleItemCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RepaymentScheduleItem:
    account = _owned_account(db, current_user, account_id)
    item = RepaymentScheduleItem(
        user_id=current_user.id,
        account_id=account.id,
        due_date=data.due_date,
        amount=data.amount,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/accounts/{account_id}/repayments/{item_id}")
def delete_repayment(
    account_id: str,
    item_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    item = (
        db.query(RepaymentScheduleItem)
        .filter(
            RepaymentScheduleItem.id == item_id,
            RepaymentScheduleItem.account_id == account_id,
            RepaymentScheduleItem.user_id == current_user.id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repayment not found")
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
