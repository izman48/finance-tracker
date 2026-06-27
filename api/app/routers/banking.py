"""Banking endpoints for Open Banking integration."""
import logging
from typing import Annotated
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import CurrentUser, verify_oauth_state
from app.schemas import (
    BankConnectionURL,
    SyncAccountsResponse,
    SyncTransactionsRequest,
    SyncTransactionsResponse,
    AccountResponse,
    TransactionResponse,
    TransactionListResponse,
    TransactionUpdate,
)
from app.services import analytics_service, categorization
from app.services.truelayer import truelayer_service
from app.models import Account, Transaction, User, BankConnection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/banking", tags=["banking"])


@router.get("/connect", response_model=BankConnectionURL)
def initiate_bank_connection(current_user: CurrentUser) -> BankConnectionURL:
    """
    Get TrueLayer authorization URL to connect bank account.

    This returns a URL that the user should visit to authorize
    access to their bank account via Open Banking.
    """
    auth_url = truelayer_service.get_auth_link(str(current_user.id))

    return BankConnectionURL(
        auth_url=auth_url,
        message="Visit this URL to connect your bank account. You'll be redirected back after authorization."
    )


@router.get("/callback")
async def oauth_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str | None = Query(None, description="OAuth authorization code"),
    state: str | None = Query(None, description="Signed OAuth state token"),
    error: str | None = Query(None, description="OAuth error if any"),
) -> RedirectResponse:
    """
    Handle TrueLayer OAuth callback.

    This endpoint receives the authorization code from TrueLayer,
    exchanges it for tokens, and redirects to the frontend.
    """
    frontend_url = get_settings().frontend_url

    # Handle OAuth errors
    if error:
        logger.error(f"OAuth error: {error}")
        return RedirectResponse(url=f"{frontend_url}/dashboard?bank_connected=false&error={error}")

    # Validate required params
    if not code or not state:
        logger.error("Missing code or state in callback")
        return RedirectResponse(url=f"{frontend_url}/dashboard?bank_connected=false&error=missing_params")

    # Verify the signed state token (CSRF protection) and extract the user_id
    try:
        user_id = verify_oauth_state(state)
    except ValueError:
        logger.error("Invalid or expired OAuth state in callback")
        return RedirectResponse(url=f"{frontend_url}/dashboard?bank_connected=false&error=invalid_state")

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error("User from OAuth state no longer exists")
            return RedirectResponse(url=f"{frontend_url}/dashboard?bank_connected=false&error=user_not_found")

        # Exchange code for tokens
        token_data = await truelayer_service.exchange_code_for_token(code)
        logger.info("Successfully exchanged OAuth code for tokens")

        # Get provider info from TrueLayer to identify which bank this is
        try:
            provider_info = await truelayer_service.get_provider_info(token_data["access_token"])
            provider_id = provider_info.get("provider_id", "unknown")
            provider_name = provider_info.get("display_name", "Unknown Bank")
            logger.info(f"Retrieved provider info: {provider_id} - {provider_name}")
        except Exception as e:
            logger.error(f"Failed to get provider info ({type(e).__name__}), using unknown")
            provider_id = "unknown"
            provider_name = "Unknown Bank"

        # Check if connection already exists for this provider
        existing_connection = db.query(BankConnection).filter(
            BankConnection.user_id == user.id,
            BankConnection.provider_id == provider_id
        ).first()

        if existing_connection:
            # Update existing connection
            existing_connection.access_token = token_data["access_token"]
            existing_connection.refresh_token = token_data.get("refresh_token")
            existing_connection.token_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=token_data["expires_in"]
            )
            bank_connection = existing_connection
            logger.info(f"Updated existing bank connection for {provider_name}")
        else:
            # Create new bank connection
            bank_connection = BankConnection(
                user_id=user.id,
                provider_id=provider_id,
                provider_name=provider_name,
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                token_expires_at=datetime.now(timezone.utc) + timedelta(
                    seconds=token_data["expires_in"]
                )
            )
            db.add(bank_connection)
            logger.info(f"Created new bank connection for {provider_name}")

        db.commit()
        db.refresh(bank_connection)

        # Immediately sync accounts and historical data with the initial access token
        # IMPORTANT: Use skip_token_refresh=True to preserve the initial token for historical data access
        # Per TrueLayer's SCA requirements, do NOT refresh the token until all historical data is fetched
        try:
            await truelayer_service.sync_accounts(bank_connection, db, skip_token_refresh=True)
            logger.info(f"Successfully synced accounts for {provider_name}")
        except Exception as e:
            error_msg = str(e)
            # Check if this is a card-only provider (AMEX, etc.) that doesn't support accounts endpoint
            if "501" in error_msg or "endpoint_not_supported" in error_msg:
                logger.warning(f"{provider_name} does not support accounts endpoint (card-only provider). Skipping account sync.")
            else:
                logger.error(f"Failed to sync accounts during callback: {error_msg}")

        # IMPORTANT: Sync maximum historical data (730 days = 2 years) with the initial token
        # Due to SCA (Strong Customer Authentication), banks only allow historical data
        # retrieval beyond 90 days within the first 45 minutes (or 5 minutes) after authentication
        # After this period, only 90 days will be available
        # NOTE: In sandbox/mock environment, banks may only return limited test data (~90 days)
        try:
            logger.info(f"Attempting to sync 730 days of historical transactions for {provider_name}")
            count = await truelayer_service.sync_transactions(bank_connection, db, days=730, skip_token_refresh=True)
            logger.info(f"Successfully synced {count} historical transactions for {provider_name}")
        except Exception as e:
            error_msg = str(e)
            # Check if this is a card-only provider that doesn't support accounts endpoint
            if "501" in error_msg or "endpoint_not_supported" in error_msg or "No accounts found" in error_msg:
                logger.warning(f"{provider_name} does not support transaction sync (card-only provider). Card support coming soon.")
            else:
                logger.error(f"Failed to sync historical transactions during callback: {error_msg}")

        return RedirectResponse(url=f"{frontend_url}/dashboard?bank_connected=true")

    except Exception as e:
        logger.error(f"Failed to exchange code: {str(e)}")
        return RedirectResponse(url=f"{frontend_url}/dashboard?bank_connected=false&error=exchange_failed")


@router.post("/sync/accounts", response_model=SyncAccountsResponse)
async def sync_accounts(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> SyncAccountsResponse:
    """
    Sync bank accounts from TrueLayer for ALL connected banks.

    Fetches all connected bank accounts and their balances,
    and stores them in the database.
    """
    # Get all bank connections for this user
    bank_connections = db.query(BankConnection).filter(
        BankConnection.user_id == current_user.id
    ).all()

    if not bank_connections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No bank connections found. Please connect a bank first."
        )

    all_accounts = []
    errors = []

    # Sync accounts for each bank connection
    for connection in bank_connections:
        try:
            accounts = await truelayer_service.sync_accounts(connection, db)
            all_accounts.extend(accounts)
            logger.info(f"Synced {len(accounts)} accounts from {connection.provider_name}")
        except Exception as e:
            logger.error(f"Failed to sync accounts for {connection.provider_name}: {str(e)}")
            errors.append(f"{connection.provider_name}: {str(e)}")

    if errors and not all_accounts:
        # All syncs failed
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync accounts: {'; '.join(errors)}"
        )

    message = f"Successfully synced {len(all_accounts)} account(s) from {len(bank_connections)} bank(s)"
    if errors:
        message += f". Errors: {'; '.join(errors)}"

    return SyncAccountsResponse(
        accounts_synced=len(all_accounts),
        accounts=[AccountResponse.model_validate(acc) for acc in all_accounts],
        message=message
    )


@router.post("/sync/transactions", response_model=SyncTransactionsResponse)
async def sync_transactions(
    request: SyncTransactionsRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> SyncTransactionsResponse:
    """
    Sync transactions from TrueLayer for ALL connected banks.

    Fetches transactions for all connected accounts and stores them.
    By default, syncs the last 90 days of transactions.
    """
    # Get all bank connections for this user
    bank_connections = db.query(BankConnection).filter(
        BankConnection.user_id == current_user.id
    ).all()

    if not bank_connections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No bank connections found. Please connect a bank first."
        )

    total_count = 0
    errors = []

    # Sync transactions for each bank connection
    for connection in bank_connections:
        try:
            count = await truelayer_service.sync_transactions(
                connection, db, days=request.days
            )
            total_count += count
            logger.info(f"Synced {count} transactions from {connection.provider_name}")
        except Exception as e:
            logger.error(f"Failed to sync transactions for {connection.provider_name}: {str(e)}")
            errors.append(f"{connection.provider_name}: {str(e)}")

    if errors and total_count == 0:
        # All syncs failed
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync transactions: {'; '.join(errors)}"
        )

    message = f"Successfully synced {total_count} new transaction(s) from {len(bank_connections)} bank(s) (last {request.days} days)"
    if errors:
        message += f". Errors: {'; '.join(errors)}"

    return SyncTransactionsResponse(
        transactions_synced=total_count,
        message=message
    )


@router.get("/accounts", response_model=list[AccountResponse])
def get_accounts(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[AccountResponse]:
    """
    Get all bank accounts for the current user.
    """
    accounts = db.query(Account).filter(Account.user_id == current_user.id).all()
    return [AccountResponse.model_validate(acc) for acc in accounts]


@router.get("/transactions", response_model=TransactionListResponse)
def get_transactions(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    account_id: str | None = Query(None, description="Filter by account ID"),
) -> TransactionListResponse:
    """
    Get transactions for the current user.

    Returns paginated list of transactions, optionally filtered by account.
    """
    # Build base query
    query = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == current_user.id)
    )

    # Filter by account if provided
    if account_id:
        query = query.filter(Account.id == account_id)

    # Order by date descending
    query = query.order_by(Transaction.transaction_date.desc())

    # Get total count
    total = query.count()

    # Paginate
    offset = (page - 1) * page_size
    transactions = query.offset(offset).limit(page_size).all()

    # Flag transactions that belong to confirmed commitments so the UI can
    # separate bills from discretionary spending.
    commitment_keys = analytics_service.commitment_match_keys(db, current_user)
    financed = analytics_service.financed_transaction_ids(db, current_user)
    items = []
    for tx in transactions:
        item = TransactionResponse.model_validate(tx)
        item.is_commitment = analytics_service.transaction_match_key(tx) in commitment_keys
        item.is_financed = tx.id in financed
        items.append(item)

    return TransactionListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/transactions/{transaction_id}", response_model=TransactionResponse)
def update_transaction(
    transaction_id: str,
    update_data: TransactionUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> TransactionResponse:
    """
    Update a transaction's category or other editable fields.

    Only allows updating transactions that belong to the current user's accounts.
    """
    # Find the transaction and verify it belongs to the user
    transaction = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id)
        .filter(Account.user_id == current_user.id)
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    # Update fields
    if update_data.category is not None:
        transaction.category = update_data.category
        # Learn the rule and spread it to this merchant's other transactions
        # (empty category = forget the rule).
        categorization.learn_and_apply(db, current_user.id, transaction)
    if update_data.subcategory is not None:
        transaction.subcategory = update_data.subcategory

    db.commit()
    db.refresh(transaction)

    return TransactionResponse.model_validate(transaction)


@router.get("/status")
def get_connection_status(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """
    Check bank connection status for the current user.
    Returns info about all connected banks.
    """
    bank_connections = db.query(BankConnection).filter(
        BankConnection.user_id == current_user.id
    ).all()

    is_connected = len(bank_connections) > 0
    connections_info = []

    for conn in bank_connections:
        # The short-lived access token auto-refreshes during syncs, so its
        # expiry is not user-relevant. Only flag connections that can no longer
        # refresh (no refresh token) — those genuinely need re-authorization.
        access_expired = bool(
            conn.token_expires_at
            and datetime.now(timezone.utc) >= conn.token_expires_at
        )
        is_expired = access_expired and not conn.refresh_token

        connections_info.append({
            "id": str(conn.id),
            "provider_name": conn.provider_name,
            "is_expired": is_expired,
            "expires_at": conn.token_expires_at.isoformat() if conn.token_expires_at else None,
            "last_synced_at": conn.last_synced_at.isoformat() if conn.last_synced_at else None,
        })

    synced_dates = [c.last_synced_at for c in bank_connections if c.last_synced_at]
    return {
        "is_connected": is_connected,
        "connections_count": len(bank_connections),
        "last_synced_at": max(synced_dates).isoformat() if synced_dates else None,
        "connections": connections_info,
        "message": (
            f"{len(bank_connections)} bank(s) connected" if is_connected
            else "No bank connections"
        )
    }


@router.post("/disconnect")
async def disconnect_all_banks(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """
    Disconnect ALL bank connections, deleting all accounts and transactions.

    This allows the user to reconnect and fetch fresh historical data.
    """
    connections = db.query(BankConnection).filter(
        BankConnection.user_id == current_user.id
    ).all()

    # Revoke each token at TrueLayer before removing the connection (best-effort),
    # then delete (cascade handles accounts and transactions).
    for connection in connections:
        if connection.access_token:
            await truelayer_service.revoke_token(connection.access_token)
        db.delete(connection)

    deleted_count = len(connections)
    db.commit()

    logger.info(f"Disconnected {deleted_count} bank(s) for user {current_user.id}")

    return {
        "success": True,
        "message": f"Disconnected {deleted_count} bank(s). All accounts and transactions have been removed."
    }


@router.delete("/connections/{connection_id}")
async def disconnect_specific_bank(
    connection_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """
    Disconnect a specific bank connection.

    This deletes the connection and all its accounts/transactions.
    """
    # Find the connection and verify it belongs to the user
    connection = db.query(BankConnection).filter(
        BankConnection.id == connection_id,
        BankConnection.user_id == current_user.id
    ).first()

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank connection not found"
        )

    # Revoke the token at TrueLayer before deleting (best-effort)
    provider_name = connection.provider_name
    if connection.access_token:
        await truelayer_service.revoke_token(connection.access_token)
    db.delete(connection)
    db.commit()

    logger.info(f"Disconnected {provider_name} for user {current_user.id}")

    return {
        "success": True,
        "message": f"Disconnected {provider_name} successfully."
    }
