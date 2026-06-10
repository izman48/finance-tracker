"""TrueLayer Open Banking API service."""
import logging
from typing import Any
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_oauth_state
from app.models import User, Account, Transaction, BankConnection

settings = get_settings()
logger = logging.getLogger(__name__)


class TrueLayerService:
    """Service for interacting with TrueLayer Open Banking API."""

    def __init__(self):
        self.client_id = settings.truelayer_client_id
        self.client_secret = settings.truelayer_client_secret
        self.redirect_uri = settings.truelayer_redirect_uri
        self.auth_url = settings.truelayer_auth_url
        self.api_url = settings.truelayer_api_url

    def get_auth_link(self, user_id: str) -> str:
        """
        Generate TrueLayer OAuth authorization URL.

        Args:
            user_id: The user ID to include in state parameter

        Returns:
            Authorization URL for the user to visit
        """
        # Permissions we're requesting (matching TrueLayer auth link builder)
        scopes = [
            "accounts",
            "balance",
            "cards",
            "direct_debits",
            "info",
            "offline_access",  # For refresh tokens
            "standing_orders",
            "transactions",
        ]

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "scope": " ".join(scopes),
            "redirect_uri": self.redirect_uri,
            # Signed, short-lived state token (CSRF protection + hides user_id)
            "state": create_oauth_state(user_id),
            "providers": "uk-ob-all uk-oauth-all",  # Live mode: removed uk-cs-mock
        }

        query_string = urlencode(params)
        return f"{self.auth_url}?{query_string}"

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from callback

        Returns:
            Token response with access_token, refresh_token, expires_in
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.auth_url}/connect/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "code": code,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """
        Refresh an expired access token.

        Args:
            refresh_token: The refresh token

        Returns:
            New token response
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.auth_url}/connect/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()

    async def get_provider_info(self, access_token: str) -> dict[str, Any]:
        """
        Get provider information from the access token.

        Args:
            access_token: Valid TrueLayer access token

        Returns:
            Provider information including provider_id and display_name
        """
        unknown = {"provider_id": "unknown", "display_name": "Unknown Bank"}

        async with httpx.AsyncClient() as client:
            # Try accounts first (most banks), then cards (AMEX/credit cards).
            for endpoint in ("accounts", "cards"):
                try:
                    response = await client.get(
                        f"{self.api_url}/data/v1/{endpoint}",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    response.raise_for_status()
                    results = response.json().get("results", [])
                    if results:
                        provider = results[0].get("provider", {})
                        provider_id = provider.get("provider_id", "unknown")
                        if provider_id != "unknown":
                            logger.info(f"Resolved provider from {endpoint}: {provider_id}")
                            return {
                                "provider_id": provider_id,
                                "display_name": provider.get("display_name", "Unknown Bank"),
                            }
                except Exception as e:
                    logger.warning(f"Provider lookup via {endpoint} failed: {type(e).__name__}")

            logger.info("Could not resolve provider info; using defaults")
            return unknown

    async def revoke_token(self, token: str) -> None:
        """Revoke an access/refresh token at TrueLayer (best-effort).

        Called on disconnect so a deleted connection's token can no longer be
        used to reach the user's bank data. Failures are logged, not raised.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.auth_url}/connect/token/revoke",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "token": token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                logger.info("Revoked TrueLayer token on disconnect")
        except Exception as e:
            logger.warning(f"Token revocation failed (continuing): {type(e).__name__}")

    async def get_accounts(self, access_token: str) -> list[dict[str, Any]]:
        """
        Fetch all accounts from TrueLayer.

        Args:
            access_token: Valid TrueLayer access token

        Returns:
            List of account data
        """
        async with httpx.AsyncClient() as client:
            logger.info(f"Fetching accounts from {self.api_url}/data/v1/accounts")
            response = await client.get(
                f"{self.api_url}/data/v1/accounts",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            logger.info(f"Accounts response status: {response.status_code}")
            if response.status_code >= 400:
                logger.error(f"Accounts response body: {response.text}")
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    async def get_cards(self, access_token: str) -> list[dict[str, Any]]:
        """
        Fetch all cards from TrueLayer.

        Args:
            access_token: Valid TrueLayer access token

        Returns:
            List of card data (formatted to look like accounts)
        """
        async with httpx.AsyncClient() as client:
            logger.info(f"Fetching cards from {self.api_url}/data/v1/cards")
            response = await client.get(
                f"{self.api_url}/data/v1/cards",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            logger.info(f"Cards response status: {response.status_code}")
            if response.status_code >= 400:
                logger.error(f"Cards response body: {response.text}")
            response.raise_for_status()
            data = response.json()
            # Format cards to look like accounts for compatibility
            cards = data.get("results", [])
            formatted_cards = []
            for card in cards:
                # Map card_type to account_type
                card_type = card.get("card_type", "CREDIT")
                if card_type == "CREDIT":
                    account_type = "CREDIT_CARD"
                elif card_type == "DEBIT":
                    account_type = "TRANSACTION"  # Debit cards are like transaction accounts
                else:
                    account_type = "OTHER"

                formatted_cards.append({
                    "account_id": card["account_id"],
                    "display_name": card.get("display_name", "Unknown Card"),
                    "account_type": account_type,
                    "currency": card.get("currency", "GBP"),
                    "card_network": card.get("card_network"),  # AMEX, VISA, etc.
                    "partial_card_number": card.get("partial_card_number"),
                })
            return formatted_cards

    async def get_account_balance(
        self, access_token: str, account_id: str
    ) -> dict[str, Any]:
        """
        Fetch balance for a specific account or card.

        Args:
            access_token: Valid TrueLayer access token
            account_id: TrueLayer account/card ID

        Returns:
            Balance data
        """
        async with httpx.AsyncClient() as client:
            # Try account balance first
            try:
                response = await client.get(
                    f"{self.api_url}/data/v1/accounts/{account_id}/balance",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [{}])[0]
            except Exception as e:
                logger.info(f"Account balance failed, trying card balance: {str(e)}")
                # Try card balance as fallback
                response = await client.get(
                    f"{self.api_url}/data/v1/cards/{account_id}/balance",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [{}])[0]

    async def get_transactions(
        self,
        access_token: str,
        account_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch transactions for an account or card.

        Args:
            access_token: Valid TrueLayer access token
            account_id: TrueLayer account/card ID
            from_date: Start date for transactions (default: 90 days ago)
            to_date: End date for transactions (default: now)

        Returns:
            List of transaction data
        """
        if from_date is None:
            from_date = datetime.now(timezone.utc) - timedelta(days=90)
        if to_date is None:
            to_date = datetime.now(timezone.utc)

        params = {
            "from": from_date.strftime("%Y-%m-%d"),
            "to": to_date.strftime("%Y-%m-%d"),
        }

        async with httpx.AsyncClient() as client:
            # Try account transactions first
            try:
                response = await client.get(
                    f"{self.api_url}/data/v1/accounts/{account_id}/transactions",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])
            except Exception as e:
                logger.info(f"Account transactions failed, trying card transactions: {str(e)}")
                # Try card transactions as fallback
                response = await client.get(
                    f"{self.api_url}/data/v1/cards/{account_id}/transactions",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])

    async def sync_accounts(self, bank_connection: BankConnection, db: Session, skip_token_refresh: bool = False) -> list[Account]:
        """
        Sync accounts from TrueLayer to database.

        Args:
            bank_connection: BankConnection object with TrueLayer tokens
            db: Database session
            skip_token_refresh: If True, skip automatic token refresh (for initial historical sync)

        Returns:
            List of synced Account objects
        """
        if not bank_connection.access_token:
            raise ValueError("Bank connection has no access token")

        # Check if token is expired and refresh if needed
        # IMPORTANT: Skip refresh during initial historical data sync (SCA requirement)
        if not skip_token_refresh and bank_connection.token_expires_at:
            if datetime.now(timezone.utc) >= bank_connection.token_expires_at:
                logger.info(f"Refreshing expired token for bank connection {bank_connection.id}")
                token_data = await self.refresh_access_token(
                    bank_connection.refresh_token
                )
                bank_connection.access_token = token_data["access_token"]
                bank_connection.refresh_token = token_data.get("refresh_token")
                bank_connection.token_expires_at = datetime.now(
                    timezone.utc
                ) + timedelta(seconds=token_data["expires_in"])
                db.commit()

        # Fetch accounts from TrueLayer (try both accounts and cards endpoints)
        tl_accounts = []

        # Try to fetch regular accounts
        try:
            tl_accounts = await self.get_accounts(bank_connection.access_token)
            logger.info(f"Fetched {len(tl_accounts)} accounts")
        except Exception as e:
            logger.warning(f"Failed to fetch accounts: {str(e)}")

        # Try to fetch cards (for AMEX, etc.)
        try:
            tl_cards = await self.get_cards(bank_connection.access_token)
            logger.info(f"Fetched {len(tl_cards)} cards")
            tl_accounts.extend(tl_cards)  # Add cards to the accounts list
        except Exception as e:
            logger.warning(f"Failed to fetch cards: {str(e)}")

        if not tl_accounts:
            raise ValueError("No accounts or cards found for this connection")

        synced_accounts = []
        for tl_account in tl_accounts:
            # Try to get balance (may not work for cards)
            balance_data = {}
            try:
                balance_data = await self.get_account_balance(
                    bank_connection.access_token, tl_account["account_id"]
                )
            except Exception as e:
                logger.warning(f"Could not fetch balance for {tl_account.get('display_name')}: {str(e)}")

            # Check if account already exists
            account = (
                db.query(Account)
                .filter(Account.external_id == tl_account["account_id"])
                .first()
            )

            if account:
                # Update existing account
                account.display_name = tl_account.get("display_name", "Unknown")
                account.account_type = tl_account.get("account_type", "TRANSACTION")
                account.currency = tl_account.get("currency", "GBP")
                account.current_balance = balance_data.get("current")
                account.available_balance = balance_data.get("available")
                account.balance_updated_at = datetime.now(timezone.utc)
            else:
                # Create new account
                account = Account(
                    user_id=bank_connection.user_id,
                    bank_connection_id=bank_connection.id,
                    external_id=tl_account["account_id"],
                    provider_name=bank_connection.provider_name,
                    account_type=tl_account.get("account_type", "TRANSACTION"),
                    display_name=tl_account.get("display_name", "Unknown"),
                    currency=tl_account.get("currency", "GBP"),
                    current_balance=balance_data.get("current"),
                    available_balance=balance_data.get("available"),
                    balance_updated_at=datetime.now(timezone.utc),
                )
                db.add(account)

            synced_accounts.append(account)

        db.commit()
        return synced_accounts

    async def sync_transactions(
        self, bank_connection: BankConnection, db: Session, days: int = 90, skip_token_refresh: bool = False
    ) -> int:
        """
        Sync transactions from TrueLayer to database.

        Args:
            bank_connection: BankConnection object with TrueLayer tokens
            db: Database session
            days: Number of days to fetch (default: 90)
            skip_token_refresh: If True, skip automatic token refresh (for initial historical sync)

        Returns:
            Number of new transactions synced
        """
        if not bank_connection.access_token:
            raise ValueError("Bank connection has no access token")

        # IMPORTANT: Skip refresh during initial historical data sync (SCA requirement)
        if not skip_token_refresh and bank_connection.token_expires_at:
            if datetime.now(timezone.utc) >= bank_connection.token_expires_at:
                logger.info(f"Refreshing expired token for bank connection {bank_connection.id}")
                token_data = await self.refresh_access_token(
                    bank_connection.refresh_token
                )
                bank_connection.access_token = token_data["access_token"]
                bank_connection.refresh_token = token_data.get("refresh_token")
                bank_connection.token_expires_at = datetime.now(
                    timezone.utc
                ) + timedelta(seconds=token_data["expires_in"])
                db.commit()

        # Get all accounts for this bank connection
        accounts = db.query(Account).filter(Account.bank_connection_id == bank_connection.id).all()

        if not accounts:
            logger.warning(f"No accounts found for bank connection {bank_connection.id}")
            return 0

        from_date = datetime.now(timezone.utc) - timedelta(days=days)
        to_date = datetime.now(timezone.utc)
        new_count = 0
        new_transactions: list[Transaction] = []

        logger.info(f"Syncing transactions from {from_date.date()} to {to_date.date()} ({days} days)")

        for account in accounts:
            # Fetch transactions from TrueLayer
            # Try to get maximum historical data first (730 days), fallback to 90 days if it fails
            logger.info(f"Fetching transactions for account {account.external_id}")
            tl_transactions = []

            # If requesting more than 90 days, try that first with fallback
            if days > 90:
                try:
                    logger.info(f"Attempting to fetch {days} days of transactions")
                    tl_transactions = await self.get_transactions(
                        bank_connection.access_token,
                        account.external_id,
                        from_date=from_date,
                    )
                    logger.info(f"Received {len(tl_transactions)} transactions from TrueLayer for account {account.external_id}")
                except Exception as e:
                    logger.warning(f"Failed to fetch {days} days, falling back to 90 days: {str(e)}")
                    # Fallback to 90 days
                    fallback_from_date = datetime.now(timezone.utc) - timedelta(days=90)
                    tl_transactions = await self.get_transactions(
                        bank_connection.access_token,
                        account.external_id,
                        from_date=fallback_from_date,
                    )
                    logger.info(f"Received {len(tl_transactions)} transactions (90 day fallback) from TrueLayer for account {account.external_id}")
            else:
                # Just fetch the requested days directly
                tl_transactions = await self.get_transactions(
                    bank_connection.access_token,
                    account.external_id,
                    from_date=from_date,
                )
                logger.info(f"Received {len(tl_transactions)} transactions from TrueLayer for account {account.external_id}")

            for tl_tx in tl_transactions:
                # Check if transaction already exists
                existing = (
                    db.query(Transaction)
                    .filter(Transaction.external_id == tl_tx["transaction_id"])
                    .first()
                )

                if existing:
                    continue  # Skip existing transactions

                # Create new transaction
                # Convert TrueLayer's uppercase transaction_type to our lowercase enum
                tx_type = tl_tx.get("transaction_type", "DEBIT").lower()

                transaction = Transaction(
                    account_id=account.id,
                    external_id=tl_tx["transaction_id"],
                    transaction_type=tx_type,
                    amount=abs(float(tl_tx["amount"])),
                    currency=tl_tx.get("currency", "GBP"),
                    description=tl_tx.get("description", ""),
                    merchant_name=tl_tx.get("merchant_name"),
                    category=tl_tx.get("transaction_category"),
                    transaction_date=datetime.fromisoformat(
                        tl_tx["timestamp"].replace("Z", "+00:00")
                    ),
                )
                db.add(transaction)
                new_transactions.append(transaction)
                new_count += 1

        # User-defined rules beat TrueLayer's generic categories.
        if new_transactions:
            from app.services import categorization

            categorization.apply_rules(db, bank_connection.user_id, new_transactions)

        bank_connection.last_synced_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Synced {new_count} new transactions for bank connection {bank_connection.id}")
        return new_count


# Singleton instance
truelayer_service = TrueLayerService()
