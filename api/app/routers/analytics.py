"""Cashflow analytics endpoints: summary, commitments review, account settings."""
import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ownership import owned_account, require_owned_account_ids
from app.core.security import CurrentUser
from app.core.oauth_tokens import SCOPE_READ, Caller, CurrentUserOrMcpRead, scoped_caller
from app.models import (
    AccountRole,
    AccountSetting,
    CommitmentRule,
    CommitmentSource,
    CommitmentStatus,
    PlannedItem,
    RepaymentScheduleItem,
    RepaymentStrategy,
)
from app.schemas import (
    MAX_HOLDING_AMOUNT,
    MAX_TARGET,
    StrictBoolQuery,
    REPAYMENT_FIELDS,
    AccountSettingUpdate,
    AssetDecomposition,
    ClaudeMarker,
    CashflowSummary,
    CommitmentCreate,
    CommitmentFromTransaction,
    CommitmentResponse,
    CommitmentUpdate,
    ForecastResponse,
    NetWorthPoint,
    NetWorthPosition,
    NudgeResponse,
    PlanFromTransaction,
    PlannedItemCreate,
    PlannedItemFlags,
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
from app.services.analytics import card_links
from app.services.claude_keep import (
    PENDING, applied_dismissals, claude_rows, commitment_keep, held_values, keep_kind, pending_ids, record_user_edit,
)
from app.services.analytics.common import _today, account_role
from app.services.analytics.repayment_warnings import card_warnings
from app.services.analytics.planned_matching import planned_states
from app.services.linked_commitments import (
    LinkedCommitmentEdit, linked_commitments, refuse_linked_edit,
)
from app.services.analytics.late_income import late_incomes
from app.services.planning_writes import claude_markers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=CashflowSummary)
def get_summary(
    current_user: CurrentUserOrMcpRead,
    db: Annotated[Session, Depends(get_db)],
) -> CashflowSummary:
    """Dashboard cashflow summary: safe-to-spend, available cash, owed, etc."""
    return CashflowSummary(**analytics_service.get_summary(db, current_user))


@router.get("/net-worth-history", response_model=list[NetWorthPoint])
def get_net_worth_history(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    months: int = 12,
    include_investments: StrictBoolQuery = "true",
) -> list[NetWorthPoint]:
    """Net worth at month-ends (bank balances reconstructed + manual assets).
    include_investments=false leaves out the investment kinds only."""
    months = max(1, min(months, 60))
    return [
        NetWorthPoint(**point)
        for point in analytics_service.net_worth_history(
            db, current_user, months, include_investments=include_investments == "true",
        )
    ]


@router.get("/net-worth-position", response_model=NetWorthPosition)
def get_net_worth_position(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> NetWorthPosition:
    """Today's net worth and how far it has moved over 1m/3m/6m/1y/all-time."""
    return NetWorthPosition(**analytics_service.net_worth_position(db, current_user))


@router.get("/net-worth-decomposition", response_model=AssetDecomposition)
def get_net_worth_decomposition(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    months: int = 12,
) -> AssetDecomposition:
    """Contribution-vs-growth split of manual-asset movement over the window
    (growth = Δvaluation − Σrecorded flows)."""
    months = max(1, min(months, 60))
    return AssetDecomposition(**analytics_service.asset_decomposition(db, current_user, months))


@router.get("/nudges", response_model=list[NudgeResponse])
def get_nudges(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[NudgeResponse]:
    """Honest, dismissible observations (cash drag, FSCS exposure). Facts with
    their arithmetic and sources — never a recommendation."""
    from app.services.budgets import budget_nudges

    nudges = analytics_service.get_nudges(db, current_user) + budget_nudges(db, current_user)
    return [NudgeResponse(**n) for n in nudges]


@router.get("/net-worth-projection", response_model=ProjectionResponse)
def get_net_worth_projection(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    target_amount: Annotated[Decimal | None, Query(ge=-MAX_TARGET, le=MAX_TARGET)] = None,
    monthly_contribution: Annotated[Decimal | None, Query(ge=-MAX_HOLDING_AMOUNT, le=MAX_HOLDING_AMOUNT)] = None,
    # The holding engine refuses a rate outside -100..50 (sec T-11-4).
    annual_growth_pct: Annotated[Decimal, Query(ge=-100, le=50)] = Decimal("5"),
    subtract_spending: bool = True,
    # Never negative: a negative estimate would raise the surplus (sec-1, T-12-0).
    monthly_spending: Annotated[Decimal | None, Query(ge=0, le=MAX_HOLDING_AMOUNT)] = None,
    # "none" is gone (owner, 2026-10-15): spending is always subtracted.
    spending_source: Literal["budgets", "average"] | None = None,
    include_investments: StrictBoolQuery = "true",
) -> ProjectionResponse:
    """Project net worth forward from stated assumptions (compound growth +
    monthly contributions). Omit monthly_contribution to derive it from the
    user's own cashflow (income − bills − everyday spending − unlinked
    holding contributions, which move into the holdings); the basis is
    echoed back. spending_source (budgets / average) picks the spending
    figure; spending is always subtracted (owner, 2026-10-15), so an old
    client's subtract_spending=false reads as budgets. See
    projections._spending_leg. A factual calculation — an estimate, not advice."""
    return ProjectionResponse(
        **analytics_service.net_worth_projection(
            db, current_user,
            target_amount=target_amount,
            monthly_contribution=monthly_contribution,
            annual_growth_pct=annual_growth_pct,
            subtract_spending=subtract_spending,
            monthly_spending=monthly_spending,
            spending_source=spending_source,
            include_investments=include_investments == "true",
        )
    )


@router.get("/forecast", response_model=ForecastResponse)
def get_forecast(
    caller: Annotated[Caller, Depends(scoped_caller(SCOPE_READ))],
    db: Annotated[Session, Depends(get_db)],
    horizon: str = "payday",
) -> ForecastResponse:
    """Balance-over-time projection across the horizon (payday|month|30|60|90).
    `budget_projection` (T-09-4) is added alongside; nothing else changes."""
    from app.services.budgets import budget_projection

    current_user = caller.user
    # A Claude token (a grant) gets plan instalments without the plan's name.
    forecast = analytics_service.get_forecast(db, current_user, horizon, for_claude=caller.grant_id is not None)
    try:
        projection, reason = budget_projection(db, current_user, forecast)
    except Exception as exc:  # BC8: the forecast still answers, unchanged
        # The type only: a message could carry a category or an amount.
        logger.error("Budget projection failed for user %s (%s)", current_user.id, type(exc).__name__)
        projection, reason = None, "unavailable"
    return ForecastResponse(**forecast, budget_projection=projection, budget_projection_reason=reason)


@router.get("/spending", response_model=SpendingResponse)
def get_spending(
    current_user: CurrentUserOrMcpRead,
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
    current_user: CurrentUserOrMcpRead,
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
    current_user: CurrentUserOrMcpRead,
    db: Annotated[Session, Depends(get_db)],
) -> list[CommitmentResponse]:
    """Detected + user commitments to review. Refreshes suggestions first.
    Income whose latest payment hasn't arrived is flagged `late` (T-08-10).
    Dismissed commitments are left out, except one Claude dismissed that is
    still pending keep (ux 9.3): it stays, with `status: dismissed` and
    `keep: pending`, until the user keeps or undoes it."""
    analytics_service.sync_suggestions(db, current_user)
    rules = (
        db.query(CommitmentRule)
        .filter(CommitmentRule.user_id == current_user.id)
        .order_by(CommitmentRule.direction, CommitmentRule.next_date)
        .all()
    )
    claude = claude_rows(db, current_user.id, [r.id for r in rules])
    applied = applied_dismissals(db, current_user.id)
    keeps = {r.id: commitment_keep(r, claude.get(r.id, []), applied) for r in rules}
    rules = [
        r for r in rules
        if r.status != CommitmentStatus.DISMISSED.value or keeps[r.id][0] == PENDING
    ]
    markers = claude_markers(db, current_user.id, "commitment", [r.id for r in rules])
    late = late_incomes(db, current_user, _today())
    linked = linked_commitments(db, current_user.id)
    return [
        CommitmentResponse.model_validate(r).model_copy(update={
            "changed_by_claude": ClaudeMarker(**markers[r.id]) if r.id in markers else None,
            "late": r.id in late,
            **dict(zip(("keep", "kept_at"), keeps[r.id])),
            "keep_kind": keep_kind(r) if keeps[r.id][0] else None,
            "keep_audit_ids": pending_ids(r, claude.get(r.id, []), applied),
            **(held_values(r, claude[r.id], applied) if keeps[r.id][0] == PENDING else {}),
            "expected_date": late[r.id].expected_date if r.id in late else None,
            "linked_liability": r.id in linked and linked[r.id].kind == "liability",
            "linked_holding": r.id in linked and linked[r.id].kind == "holding",
            "linked_mortgage": r.id in linked and linked[r.id].mortgage,
        })
        for r in rules
    ]


@router.post("/commitments/from-transaction", response_model=CommitmentResponse, status_code=status.HTTP_201_CREATED)
def commitment_from_transaction(
    data: CommitmentFromTransaction,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CommitmentRule:
    """Mark a transaction as recurring → a confirmed commitment."""
    try:
        rule = analytics_service.commitment_from_transaction(
            db, current_user, str(data.transaction_id), data.cadence
        )
    except LinkedCommitmentEdit as refused:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refused.owner.detail) from None
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
    require_owned_account_ids(db, current_user, data)
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
    commitment_id: uuid.UUID,
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
    require_owned_account_ids(db, current_user, data)

    updates = data.model_dump(exclude_unset=True)
    refuse_linked_edit(db, current_user.id, rule.id, updates)
    # match_merchant is a virtual field — translate it into the stored match_key.
    if "match_merchant" in updates:
        merchant = updates.pop("match_merchant")
        direction = updates.get("direction") or rule.direction
        rule.match_key = analytics_service.merchant_match_key(direction, merchant)
    if "card_account_id" in updates:
        rule.card_link_source = card_links.USER
    # sync_suggestions re-derives a detected rule's match_key from its label.
    # A user's rename must not do that (T-08-18): their payments would stop
    # matching and the merchant would be suggested again. A manual rule's key
    # is left alone, the same as for Claude's renames (T-08-9).
    if (
        "label" in updates
        and updates["label"] != rule.label
        and rule.source == CommitmentSource.DETECTED.value
    ):
        # A manual rule without a key falls back to its label's: store the
        # old label's key first (older detected rows have none). A keyless
        # *manual* rule is not frozen here, unlike Claude's rename (#127):
        # it matches by its label by design, and renaming it is the user's
        # own choice of what it should match.
        rule.match_key = rule.match_key or analytics_service.merchant_match_key(rule.direction, rule.label)
        rule.source = CommitmentSource.MANUAL.value
    for field, value in updates.items():
        setattr(rule, field, value)
    # The fields set here are now the user's, not Claude's (T-08-20). This
    # is not keeping Claude's other changes (owner, Q-D4).
    record_user_edit(db, current_user.id, rule.id, updates.keys())
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
    try:
        refuse_linked_edit(db, current_user.id, uuid.UUID(commitment_id), {"next_date"})
    except ValueError:
        pass  # not an id: skip_commitment answers 404
    rule = analytics_service.skip_commitment(db, current_user, commitment_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commitment not found")
    return rule


@router.get("/planned-items", response_model=list[PlannedItemResponse])
def list_planned_items(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[PlannedItemResponse]:
    items = (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == current_user.id, PlannedItem.active.is_(True))
        .order_by(PlannedItem.start_date)
        .all()
    )
    markers = claude_markers(db, current_user.id, "planned_event", [i.id for i in items])
    states = planned_states(db, current_user, items, _today())
    return [
        PlannedItemResponse.model_validate(i).model_copy(update={
            "changed_by_claude": ClaudeMarker(**markers[i.id]) if i.id in markers else None,
            "matched_transaction_id": states[i.id].matched_transaction_id if i.id in states else None,
            "late": states[i.id].late if i.id in states else False,
            "overdue": states[i.id].overdue if i.id in states else False,
        })
        for i in items
    ]


@router.post("/planned-items", response_model=PlannedItemResponse, status_code=status.HTTP_201_CREATED)
def create_planned_item(
    data: PlannedItemCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PlannedItem:
    require_owned_account_ids(db, current_user, data)
    item = PlannedItem(user_id=current_user.id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/planned-items/{item_id}", response_model=PlannedItemResponse)
def update_planned_item_flags(
    item_id: uuid.UUID,
    data: PlannedItemFlags,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PlannedItem:
    """The user ticks or unticks "Card payment" (T-12-4a). Web only; another
    user's or an unknown item is a 404."""
    item = (
        db.query(PlannedItem)
        .filter(PlannedItem.id == item_id, PlannedItem.user_id == current_user.id, PlannedItem.active.is_(True))
        .first()
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned item not found")
    item.is_card_payment = data.is_card_payment
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


@router.get("/accounts/{account_id}/repayments", response_model=list[RepaymentScheduleItemResponse])
def list_repayments(
    account_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[RepaymentScheduleItem]:
    """Scheduled repayments for a credit account (for the `scheduled` strategy)."""
    owned_account(db, current_user, account_id)
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
    account_id: uuid.UUID,
    data: RepaymentScheduleItemCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RepaymentScheduleItem:
    account = owned_account(db, current_user, account_id)
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
    account_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    owned_account(db, current_user, account_id)
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
    account_id: uuid.UUID,
    data: AccountSettingUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Upsert an account's cashflow settings (role, overdraft, repayment config)."""
    account = owned_account(db, current_user, account_id)
    require_owned_account_ids(db, current_user, data)

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

    updates = data.model_dump(exclude_unset=True)
    _check_repayment_settings(account, setting, updates)
    for field, value in updates.items():
        setattr(setting, field, value)
    db.commit()

    return {
        "success": True,
        "message": "Account settings updated",
        # ux A1: notes about the saved settings (T-10-5); [] when there are none.
        "warnings": card_warnings(db, current_user, account, setting),
    }


def _check_repayment_settings(account, setting: AccountSetting, updates: dict) -> None:
    """422 unless the patched settings make sense (T-10-4a):
    - repayment fields only on a credit account (the role after the patch);
    - `scheduled` only on a card the user marked as instalment-type. A card
      already on `scheduled` may still be edited (the "fix this" notice asks
      the user to move it); switching to it, or unmarking the card while on
      it, is refused."""
    role = updates.get("role") or account_role(account, setting).value
    if role != AccountRole.CREDIT.value and any(updates.get(f) is not None for f in REPAYMENT_FIELDS):
        raise HTTPException(status_code=422, detail="Repayment settings are only for credit cards.")
    strategy = updates.get("repayment_strategy", setting.repayment_strategy)
    instalment = updates.get("instalment_card", bool(setting.instalment_card))
    if strategy != RepaymentStrategy.SCHEDULED.value or instalment:
        return
    switching = updates.get("repayment_strategy", setting.repayment_strategy) != setting.repayment_strategy
    unmarking = "instalment_card" in updates and bool(setting.instalment_card)
    if switching or unmarking:
        raise HTTPException(
            status_code=422,
            detail="Scheduled payments are only for instalment cards. Mark the card as one, or pick another option.",
        )
